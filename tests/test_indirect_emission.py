"""外购电间接排放 (Scope 2) 与运输周转量碳强度计算测试"""
import pytest
from src.engine.calculator import VehicleGroupData
from src.engine.indirect_emission import (
    GRID_EMISSION_FACTORS,
    get_grid_factor,
    calculate_indirect_emission,
    calculate_freight_turnover,
)

def test_grid_emission_factors_official_values():
    """验证官方公告 2025年 第47号 中核心电网排放因子数值准确性"""
    # 全国平均
    assert GRID_EMISSION_FACTORS["全国平均"] == 0.5306
    assert GRID_EMISSION_FACTORS["全国平均(扣除非化石)"] == 0.6096
    assert GRID_EMISSION_FACTORS["全国化石电力"] == 0.8273

    # 六大区域
    assert GRID_EMISSION_FACTORS["华北区域"] == 0.6361
    assert GRID_EMISSION_FACTORS["南方区域"] == 0.4042
    assert GRID_EMISSION_FACTORS["西南区域"] == 0.2472

    # 关键省份
    assert GRID_EMISSION_FACTORS["北京"] == 0.5554
    assert GRID_EMISSION_FACTORS["上海"] == 0.5737
    assert GRID_EMISSION_FACTORS["广东"] == 0.4419
    assert GRID_EMISSION_FACTORS["江苏"] == 0.5827

def test_get_grid_factor_lookup():
    """验证电网因子查找及自定义覆写"""
    assert get_grid_factor("全国平均") == 0.5306
    assert get_grid_factor("广东") == 0.4419
    assert get_grid_factor("未知地区") == 0.5306  # 兜底全国平均
    assert get_grid_factor("北京", custom_factor=0.35) == 0.35  # 自定义绿电因子

def test_indirect_emission_pure_diesel_fleet():
    """纯柴油车队无新能源车时，购电间接排放应为 0"""
    fleet = [
        VehicleGroupData(vehicle_type="重型柴油货车", count=10, annual_km=50000, load_factor=0.8),
    ]
    res = calculate_indirect_emission(fleet, grid_key="全国平均")
    assert res.total_electricity_kwh == 0.0
    assert res.indirect_emission_tco2 == 0.0
    assert res.electric_vehicle_count == 0

def test_indirect_emission_electric_fleet():
    """新能源车队正常核算 Scope 2 间接排放量"""
    fleet = [
        VehicleGroupData(vehicle_type="新能源物流车", count=20, annual_km=30000, load_factor=0.75),
    ]
    # 20 辆 * 30,000 km * 0.35 kWh/km = 210,000 kWh
    # 广东电网 0.4419 kgCO2/kWh -> 210,000 * 0.4419 / 1000 = 92.799 -> 92.80 tCO2e
    res = calculate_indirect_emission(fleet, grid_key="广东")
    assert res.total_electricity_kwh == 210000.0
    assert res.electric_vehicle_count == 20
    assert res.grid_name == "广东"
    assert res.grid_factor == 0.4419
    assert pytest.approx(res.indirect_emission_tco2, abs=0.05) == 92.80

def test_freight_turnover_and_intensity():
    """验证运输周转量及单位货物周转量排放强度 (gCO2 / t·km)"""
    fleet = [
        # 10 辆重型柴油货车 (额定 25t), 年里程 100,000 km, 满载率 0.80
        # 吨公里 = 10 * 100,000 * 25 * 0.8 = 20,000,000 t·km (2000 万吨公里)
        VehicleGroupData(vehicle_type="重型柴油货车", count=10, annual_km=100000, load_factor=0.80),
    ]
    direct_emission_t = 877.0  # 假设直接排放 877 吨
    indirect_emission_t = 0.0

    res = calculate_freight_turnover(fleet, direct_emission_t, indirect_emission_t)
    assert res.total_turnover_tkm == 20000000.0
    assert res.total_turnover_wan_tkm == 2000.0
    # 强度 = 877 * 1,000,000 / 20,000,000 = 43.85 gCO2 / t·km
    assert pytest.approx(res.scope1_intensity_g_per_tkm, abs=0.01) == 43.85
    assert res.scope2_intensity_g_per_tkm == 0.0
    assert pytest.approx(res.total_intensity_g_per_tkm, abs=0.01) == 43.85

def test_freight_turnover_zero_safe():
    """零周转量防御测试，避免除以零错误"""
    fleet = []
    res = calculate_freight_turnover(fleet, direct_emission_t=0.0)
    assert res.total_turnover_tkm == 0.0
    assert res.total_intensity_g_per_tkm == 0.0
