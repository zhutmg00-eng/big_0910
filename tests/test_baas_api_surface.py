"""车电分离（BaaS）口径必须能从 API 与 UI 走到。

背景：BaaS 是项目对外主打的卖点（「初始垫资降约 70%」），但 v0.4 之前
只有 ``scripts/`` 下的分析脚本能算出来——``VehicleTCORunRequest`` 没有
BaaS 字段（pydantic 默认忽略未知字段，传 ``is_baas_mode: true`` 会被静默
丢弃并返回买断口径的 ``delta_capex_total_yuan``），``analyze_reduction_scenario``
也不接受经济参数，UI 因此永远只能显示买断账。

这组测试锁定三件事：
1. 请求模型真的接受 BaaS 字段，缺省时仍按买断口径（向后兼容）；
2. 引擎在 BaaS 下给出的初始投资与回收期确实与买断不同；
3. 减排情景这条链路能把外部传入的经济参数透传到 TCO 结果。
"""

from __future__ import annotations

import pytest

from src.engine.reduction import analyze_reduction_scenario
from src.engine.tco import TCOEconomicParameters, calculate_single_vehicle_tco
from src.models.tco import VehicleTCORunRequest


BASE_FORM = dict(vehicle_type="重型柴油货车", replace_count=10, annual_km=100000)


class TestRequestModelAcceptsBaasFields:
    def test_baas_off_by_default(self):
        """不传 BaaS 字段时必须是买断口径——老调用方不能被动改口径。"""
        req = VehicleTCORunRequest(**BASE_FORM)
        assert req.is_baas_mode is False
        assert req.baas_chassis_discount_wan is None
        assert req.baas_annual_battery_rental_yuan is None

    def test_baas_fields_survive_validation(self):
        """回归：pydantic 默认会静默丢弃模型里没声明的字段。"""
        req = VehicleTCORunRequest(
            **BASE_FORM, is_baas_mode=True, baas_annual_battery_rental_yuan=45000
        )
        assert req.is_baas_mode is True
        assert req.baas_annual_battery_rental_yuan == 45000

    @pytest.mark.parametrize("bad", [-1, -0.01, -100000])
    def test_negative_rental_rejected(self, bad):
        with pytest.raises(Exception):
            VehicleTCORunRequest(**BASE_FORM, baas_annual_battery_rental_yuan=bad)

    @pytest.mark.parametrize("bad", [-1, -20])
    def test_negative_chassis_discount_rejected(self, bad):
        with pytest.raises(Exception):
            VehicleTCORunRequest(**BASE_FORM, baas_chassis_discount_wan=bad)


class TestEngineBaasDiffersFromBuyout:
    def _run(self, **econ_kw):
        econ = TCOEconomicParameters(
            diesel_price_yuan_per_l=7.50, electricity_price_yuan_per_kwh=1.00, **econ_kw
        )
        return calculate_single_vehicle_tco(econ_params=econ, annual_co2_reduction_t=0.0, **BASE_FORM)

    def test_baas_cuts_initial_capex_and_payback(self):
        buyout = self._run()
        baas = self._run(is_baas_mode=True)
        assert baas.delta_capex_total_yuan < buyout.delta_capex_total_yuan
        assert baas.payback_period_years < buyout.payback_period_years

    def test_rental_reduces_opex_saving(self):
        """租金越高，年运营节省越少、回收期越长——不是比例不变的空结论。"""
        cheap = self._run(is_baas_mode=True, baas_annual_battery_rental_yuan=0)
        pricey = self._run(is_baas_mode=True, baas_annual_battery_rental_yuan=90000)
        assert pricey.annual_opex_saving_total_yuan < cheap.annual_opex_saving_total_yuan
        assert pricey.payback_period_years > cheap.payback_period_years

    def test_baas_carries_the_identity_note(self):
        """70% 是代数恒等式的算术结果，必须随结果一起返回。"""
        baas = self._run(is_baas_mode=True)
        assert baas.baas_capex_note
        assert "恒等式" in baas.baas_capex_note
        assert self._run().baas_capex_note == ""


class TestReductionScenarioForwardsEconParams:
    def _fleet(self):
        from src.engine.calculator import VehicleGroupData

        return [VehicleGroupData("重型柴油货车", 10, 100000, 0.85)]

    def test_default_stays_buyout(self):
        res = analyze_reduction_scenario(self._fleet(), {"替换为新能源物流车": 10}).to_dict()
        tco = res.get("tco_analysis") or {}
        assert tco.get("total_delta_capex_wan") == pytest.approx(330.0, abs=0.1)

    def test_econ_params_reach_the_tco_block(self):
        res = analyze_reduction_scenario(
            self._fleet(),
            {"替换为新能源物流车": 10},
            econ_params=TCOEconomicParameters(is_baas_mode=True),
        ).to_dict()
        tco = res.get("tco_analysis") or {}
        assert tco.get("total_delta_capex_wan") == pytest.approx(100.0, abs=0.1)

    def test_baas_note_reaches_scenario_output(self):
        res = analyze_reduction_scenario(
            self._fleet(),
            {"替换为新能源物流车": 10},
            econ_params=TCOEconomicParameters(is_baas_mode=True),
        ).to_dict()
        by_type = (res.get("tco_analysis") or {}).get("by_vehicle_type") or {}
        notes = [v.get("baas_capex_note", "") for v in by_type.values()]
        assert any("恒等式" in n for n in notes), f"情景输出未带 BaaS 口径说明: {notes}"

    def test_load_only_scenario_unaffected(self):
        """纯满载率措施不产生 TCO 替换，传 BaaS 也不应报错或改口径。

        基线取 0.60 而非 0.85：满载率调节函数只在低于阈值
        LOAD_FACTOR_THRESHOLD=0.75 时才起作用，0.85 提升到 0.90
        减排量恒为 0，那样的用例测不出任何东西。
        """
        from src.engine.calculator import VehicleGroupData

        fleet = [VehicleGroupData("重型柴油货车", 10, 100000, 0.60)]
        res = analyze_reduction_scenario(
            fleet,
            {"提升满载率至0.9": 10},
            econ_params=TCOEconomicParameters(is_baas_mode=True),
        ).to_dict()
        assert res["reduction_t"] > 0
