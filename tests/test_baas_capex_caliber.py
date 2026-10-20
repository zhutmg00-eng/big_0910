"""BaaS「初始垫资骤降 70%」这个卖点的口径守卫。

背景：答辩材料三处把 BaaS 说成"垫资骤降 70%"，但核到引擎里发现这个比例
不是敏感性分析的结论，而是代数恒等式的算术结果：

    买断 单车增量 = (ev_车价 − ice_车价) + 充电桩单价
    BaaS 单车增量 = (ev_车价 − ice_车价) − 电池剥离立减

重卡基准：ev−ice = 30 万、充电桩 3 万、立减 20 万
    → 买断 33 万/车、BaaS 10 万/车 → 降幅 = (33−10)/33 = 69.7%

关键点：这个比例**与电池租金、年里程、油价电价全都无关**。改充电桩单价假设就能
让它滑动（1 万→67.7%、2 万→68.8%、3 万→69.7%、5 万→71.4%）。所以引用"70%"时
必须同时披露充电桩成本假设，否则评委会问"你这 70% 是怎么来的"而答不上来。

这些测试守住三件事：
1. 引擎确实算得出 1.476 年 / 69.7%（数字本身没写错）；
2. 该比例只受车价与充电桩单价影响，不受租金/里程/能源价格影响（证明是恒等式）；
3. 引擎会主动产出 baas_capex_note 把这个口径讲清楚，非 BaaS 模式不产噪音。
"""
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.engine.tco import (  # noqa: E402
    TCOEconomicParameters,
    calculate_single_vehicle_tco,
    get_tco_benchmark,
)

HEAVY = "重型柴油货车"
COUNT = 10
KM = 100000


def _baas(rental=45000.0, elec=1.00, diesel=7.50, discount=0.0):
    return TCOEconomicParameters(
        diesel_price_yuan_per_l=diesel,
        electricity_price_yuan_per_kwh=elec,
        is_baas_mode=True,
        baas_chassis_discount_wan=discount,
        baas_annual_battery_rental_yuan=rental,
    )


def _run(params=None, km=KM):
    return calculate_single_vehicle_tco(
        HEAVY,
        replace_count=COUNT,
        annual_km=km,
        annual_co2_reduction_t=0.0,
        econ_params=params,
    )


class TestBaselineReproducesDocumentedNumbers:
    """答辩材料写的 2.90 年 / 1.46 年必须能从引擎真实复现，否则就是编的。

    【口径踩坑记录】这里必须显式传电价。
    `TCOEconomicParameters` 的默认电价是 0.8 元/kWh，而答辩材料与
    `docs/derived_metrics.json` 的口径是 1.00 元/kWh。只传柴油价 7.50、
    漏传电价时回收期算出来是 2.3446 年而不是 2.9268 年——差值全部来自
    电价假设，不是公式错。为此本类里买断基线显式给出 BUYOUT_PARAMS，
    且下面专门加了 `test_default_electricity_price_differs_from_documented`
    把这个易踩的默认值差异锁死，避免有人"清理"成不传参数。
    """

    # 与答辩材料 / derived_metrics 一致的口径：柴油 7.50 元/L、电 1.00 元/kWh
    BUYOUT_PARAMS = TCOEconomicParameters(
        diesel_price_yuan_per_l=7.50,
        electricity_price_yuan_per_kwh=1.00,
    )

    def test_buyout_payback_matches_documented_2_90(self):
        r = _run(self.BUYOUT_PARAMS)
        assert r.delta_capex_total_yuan == pytest.approx(3_300_000)
        assert r.payback_period_years == pytest.approx(2.927, abs=0.01)

    def test_baas_payback_matches_documented_1_46(self):
        r = _run(_baas())
        assert r.delta_capex_total_yuan == pytest.approx(1_000_000)
        assert r.payback_period_years == pytest.approx(1.476, abs=0.01)

    def test_default_electricity_price_differs_from_documented(self):
        """锁死默认电价 0.8 ≠ 材料口径 1.0，防止有人删掉显式参数。"""
        default_elec = TCOEconomicParameters().electricity_price_yuan_per_kwh
        assert default_elec == pytest.approx(0.8)
        assert default_elec != pytest.approx(
            self.BUYOUT_PARAMS.electricity_price_yuan_per_kwh), (
            "默认电价若改成 1.0，请同步更新答辩材料与 derived_metrics 的口径说明"
        )
        r_default = _run()
        r_doc = _run(self.BUYOUT_PARAMS)
        # 默认电价更低 → 电费更省 → 回收期更短
        assert r_default.payback_period_years < r_doc.payback_period_years


class TestCapexRatioIsArithmeticIdentity:
    """证明 70% 不是算出来的结论，而是代数恒等式的算术结果。"""

    def test_ratio_unchanged_by_battery_rental(self):
        """电池租金翻 4 倍，垫资降幅纹丝不动——因为它根本不含租金项。"""
        ratios = []
        for rental in (0.0, 45000.0, 90000.0, 180000.0):
            r = _run(_baas(rental=rental))
            buyout = _run().delta_capex_total_yuan
            ratios.append(r.delta_capex_total_yuan / buyout)
        assert len(set(round(x, 10) for x in ratios)) == 1, (
            f"租金变化不该影响 BaaS/买断 垫资比，实得 {ratios}"
        )

    def test_ratio_unchanged_by_mileage(self):
        """年里程 5 万 vs 20 万，垫资降幅不变（垫资与里程无关）。"""
        buyout = _run(km=50000).delta_capex_total_yuan
        for km in (50000, 100000, 200000):
            r = _run(_baas(), km=km)
            assert r.delta_capex_total_yuan / buyout == pytest.approx(1 / 3.3, abs=1e-9)

    def test_ratio_unchanged_by_energy_prices(self):
        """油价电价变动不影响垫资降幅（只影响 ΔOPEX 和回收期）。"""
        buyout = _run().delta_capex_total_yuan
        base = _run(_baas()).delta_capex_total_yuan / buyout
        for diesel, elec in ((6.0, 0.5), (9.0, 1.8), (7.5, 2.5)):
            r = _run(_baas(elec=elec, diesel=diesel))
            assert r.delta_capex_total_yuan / buyout == pytest.approx(base)

    def test_ratio_tracks_charger_cost_assumption(self):
        """改充电桩单价假设，降幅就滑动——这正是必须披露该假设的原因。"""
        spec = get_tco_benchmark(HEAVY)
        observed = {}
        for charger in (1.0, 2.0, 3.0, 5.0):
            buyout_per_veh = (
                spec.ev_vehicle_price_wan - spec.ice_vehicle_price_wan + charger
            )
            baas_per_veh = spec.ev_vehicle_price_wan - 20.0 - spec.ice_vehicle_price_wan
            observed[charger] = (buyout_per_veh - baas_per_veh) / buyout_per_veh * 100

        # 3 万档必须等于文档里的 ~70%
        assert observed[3.0] == pytest.approx(69.7, abs=0.1)
        # 且必须确实随假设变化（不是恒定 70%）
        assert observed[1.0] < observed[3.0] < observed[5.0]

    def test_baas_per_vehicle_delta_is_price_difference_minus_discount(self):
        """BaaS 单车增量恒等于 (ev−ice)−立减，与任何运营参数无关。"""
        spec = get_tco_benchmark(HEAVY)
        expected_wan = spec.ev_vehicle_price_wan - 20.0 - spec.ice_vehicle_price_wan
        for km in (30000, 100000, 200000):
            r = _run(_baas(), km=km)
            assert r.delta_capex_per_vehicle_yuan == pytest.approx(expected_wan * 10000)


class TestBaasCapexNote:
    """引擎必须主动把"这个比例是恒等式"讲出来，而不是留给读者猜。"""

    def test_baas_mode_emits_explanatory_note(self):
        r = _run(_baas())
        note = r.baas_capex_note
        assert note, "BaaS 模式必须产出口径说明"
        assert "69.7" in note
        assert "代数恒等式" in note
        # 必须点明真正决定这个比例的两个量
        assert "充电桩" in note
        assert "电池租金" in note
        # 必须明确它不是敏感性分析结论
        assert "敏感性" in note

    def test_note_discloses_charger_assumption_value(self):
        r = _run(_baas())
        spec = get_tco_benchmark(HEAVY)
        assert f"{spec.charger_cost_wan:.1f}" in r.baas_capex_note, (
            "口径说明里必须写出实际采用的充电桩成本假设值"
        )

    def test_buyout_mode_has_no_note(self):
        r = _run()
        assert r.baas_capex_note == "", "买断模式不该有 BaaS 口径说明"

    def test_note_reaches_to_dict(self):
        """UI 与 API 走 to_dict，说明必须能传出去，否则等于没写。"""
        from src.engine.tco import calculate_fleet_tco

        # calculate_fleet_tco 的 replacements 是 dict 列表（内部按
        # item["vehicle_type"] 取值），传 VehicleGroupData 会 TypeError。
        replacements = [{
            "vehicle_type": HEAVY,
            "replace_count": COUNT,
            "annual_km": KM,
            "annual_co2_reduction_t": 0.0,
        }]
        result = calculate_fleet_tco(replacements, econ_params=_baas())
        payload = result.to_dict()
        note = payload["by_vehicle_type"][HEAVY]["baas_capex_note"]
        assert note, "to_dict 必须把 baas_capex_note 透出给前端"
        assert "代数恒等式" in note


# ---------------------------------------------------------------- 论文表 6 可复现性

# 论文 6.3.2 表 6 的完整参数假设。此前版本只给了回收期、没给电价与电池租金，
# 导致任何人都无法复算，也无法判断 0.97 年是否与引擎默认档一致。
PAPER_LIGHT_PARAMS = TCOEconomicParameters(
    diesel_price_yuan_per_l=7.50,
    electricity_price_yuan_per_kwh=0.80,  # 论文披露值；引擎默认同为 0.80
    is_baas_mode=True,
    baas_annual_battery_rental_yuan=13500.0,  # 论文披露值，高于轻型内置档 12,000
)


def test_paper_table6_light_truck_row_is_reproducible():
    """论文表 6 BaaS 行：1.00 万初始增量 / 1.03 万年结余 / 0.97 年回收期。"""
    r = calculate_single_vehicle_tco(
        "轻型柴油货车",
        replace_count=1,
        annual_km=35000,
        annual_co2_reduction_t=0.0,
        econ_params=PAPER_LIGHT_PARAMS,
    )
    assert r.delta_capex_total_yuan == pytest.approx(10000.0, abs=1.0)
    assert r.annual_opex_saving_total_yuan == pytest.approx(10300.0, abs=1.0)
    assert r.payback_period_years == pytest.approx(0.97, abs=0.01)


def test_paper_table6_buyout_row_is_reproducible():
    """论文表 6 买断行：6.80 万初始增量 / 2.38 万年结余 / 2.86 年回收期。"""
    import dataclasses

    params = dataclasses.replace(PAPER_LIGHT_PARAMS, is_baas_mode=False)
    r = calculate_single_vehicle_tco(
        "轻型柴油货车",
        replace_count=1,
        annual_km=35000,
        annual_co2_reduction_t=0.0,
        econ_params=params,
    )
    assert r.delta_capex_total_yuan == pytest.approx(68000.0, abs=1.0)
    assert r.annual_opex_saving_total_yuan == pytest.approx(23800.0, abs=1.0)
    assert r.payback_period_years == pytest.approx(2.86, abs=0.01)


def test_paper_discloses_rental_is_above_builtin_default():
    """论文必须披露 1.35 万租金高于轻型内置档 12,000，否则读者会误以为是默认值。"""
    import dataclasses

    default_rent = dataclasses.replace(PAPER_LIGHT_PARAMS, baas_annual_battery_rental_yuan=0.0)
    r_default = calculate_single_vehicle_tco(
        "轻型柴油货车", replace_count=1, annual_km=35000, annual_co2_reduction_t=0.0,
        econ_params=default_rent,
    )
    # 内置档 12,000 时回收期更短，说明 13,500 是一个更保守的选择，而不是笔误
    assert r_default.payback_period_years < 0.97
    assert r_default.payback_period_years == pytest.approx(0.85, abs=0.01)
