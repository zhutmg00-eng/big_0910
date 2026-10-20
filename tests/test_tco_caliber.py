"""TCO 经济账口径：负能耗节省、同车型多记录合并。"""
from __future__ import annotations

import pytest

from src.engine.tco import (
    TCOEconomicParameters,
    calculate_fleet_tco,
    calculate_single_vehicle_tco,
)


# ============================================================
# 能耗节省不得被截断为 0
# ============================================================

def test_energy_saving_can_be_negative_when_electricity_is_expensive():
    """高电价下电车电费可高于油费，此时必须如实给出负的能耗节省。"""
    params = TCOEconomicParameters(electricity_price_yuan_per_kwh=1.80)
    res = calculate_single_vehicle_tco(
        vehicle_type="重型柴油货车",
        replace_count=10,
        annual_km=80000,
        annual_co2_reduction_t=500.0,
        econ_params=params,
    )
    # 油费 198000 元/车/年，电费 201600 元/车/年
    assert res.annual_fuel_cost_per_vehicle_yuan == pytest.approx(198000.0)
    assert res.annual_elec_cost_per_vehicle_yuan == pytest.approx(201600.0)
    real_per_vehicle = (
        res.annual_fuel_cost_per_vehicle_yuan - res.annual_elec_cost_per_vehicle_yuan
    )
    assert real_per_vehicle < 0
    # 车队能耗节省 = 单车差额 × 车辆数，不得被截断掉负号
    assert res.annual_energy_saving_total_yuan == pytest.approx(real_per_vehicle * 10)


def test_cheap_electricity_keeps_positive_saving():
    params = TCOEconomicParameters(electricity_price_yuan_per_kwh=0.80)
    res = calculate_single_vehicle_tco("重型柴油货车", 10, 80000, 500.0, econ_params=params)
    assert res.annual_energy_saving_total_yuan > 0
    assert res.payback_period_years is not None
    assert res.payback_period_years > 0


def test_unrecoverable_case_reports_no_payback():
    """ΔOPEX 为负时不存在静态回收期，必须返回 None 而不是负数或 0。"""
    params = TCOEconomicParameters(electricity_price_yuan_per_kwh=2.50)
    res = calculate_single_vehicle_tco("重型柴油货车", 10, 80000, 500.0, econ_params=params)
    assert res.annual_opex_saving_total_yuan < 0
    assert res.payback_period_years is None


def test_mac_reflects_true_economics():
    """能耗差额为负时，MAC 应体现为正的减排成本而非负成本。"""
    cheap = calculate_single_vehicle_tco(
        "重型柴油货车", 10, 80000, 500.0,
        econ_params=TCOEconomicParameters(electricity_price_yuan_per_kwh=0.80),
    )
    pricey = calculate_single_vehicle_tco(
        "重型柴油货车", 10, 80000, 500.0,
        econ_params=TCOEconomicParameters(electricity_price_yuan_per_kwh=1.80),
    )
    assert cheap.mac_yuan_per_tco2e < pricey.mac_yuan_per_tco2e


# ============================================================
# 同车型多记录必须合并，不能后覆盖前
# ============================================================

def test_same_vehicle_type_records_are_merged_not_overwritten():
    replacements = [
        {"vehicle_type": "重型柴油货车", "replace_count": 10,
         "annual_km": 80000, "annual_co2_reduction_t": 500.0},
        {"vehicle_type": "重型柴油货车", "replace_count": 10,
         "annual_km": 50000, "annual_co2_reduction_t": 300.0},
    ]
    fleet = calculate_fleet_tco(replacements)
    merged = fleet.by_vehicle_type["重型柴油货车"]

    assert fleet.total_replace_count == 20
    assert merged.replace_count == 20  # 旧实现只会剩第二条的 10

    # 分车型明细必须与车队合计自洽
    assert merged.annual_co2_reduction_t == pytest.approx(fleet.total_annual_co2_reduction_t)
    assert merged.delta_capex_total_yuan == pytest.approx(fleet.total_delta_capex_yuan)
    assert merged.annual_opex_saving_total_yuan == pytest.approx(
        fleet.total_annual_opex_saving_yuan
    )
    assert merged.lifespan_co2_reduction_t == pytest.approx(
        fleet.total_lifespan_co2_reduction_t
    )


def test_different_vehicle_types_stay_separate():
    replacements = [
        {"vehicle_type": "重型柴油货车", "replace_count": 5,
         "annual_km": 80000, "annual_co2_reduction_t": 200.0},
        {"vehicle_type": "中型柴油货车", "replace_count": 5,
         "annual_km": 50000, "annual_co2_reduction_t": 100.0},
    ]
    fleet = calculate_fleet_tco(replacements)
    assert set(fleet.by_vehicle_type) == {"重型柴油货车", "中型柴油货车"}
    assert fleet.total_replace_count == 10


def test_zero_count_replacement_is_skipped():
    fleet = calculate_fleet_tco([
        {"vehicle_type": "重型柴油货车", "replace_count": 0,
         "annual_km": 80000, "annual_co2_reduction_t": 0.0},
    ])
    assert fleet.total_replace_count == 0
    assert fleet.by_vehicle_type == {}
