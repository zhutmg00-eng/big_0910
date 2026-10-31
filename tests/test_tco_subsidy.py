"""老旧营运货车报废更新补贴（P1-3）接入 TCO 引擎的测试。

口径约定：补贴只抵减初始投资增量 ΔCAPEX，不改变能耗节省与减排量；
默认 0 不启用，全部既有 TCO 结论不变。
"""
import sys
from pathlib import Path

import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.engine.tco import (
    SCRAPPAGE_SUBSIDY_COMBINED_CAP,
    SCRAPPAGE_SUBSIDY_SCHEDULE,
    TCOEconomicParameters,
    calculate_single_vehicle_tco,
    lookup_scrappage_subsidy,
)


def test_default_no_subsidy_keeps_existing_numbers():
    """默认（补贴=0）时结果与既有口径完全一致：轻卡买断回收期 2.86 年。"""
    res = calculate_single_vehicle_tco(
        vehicle_type="轻型柴油货车",
        replace_count=1,
        annual_km=35000,
        annual_co2_reduction_t=2.6573,
    )
    assert res.payback_period_years == pytest.approx(2.86, abs=0.01)
    assert res.policy_subsidy_note == ""


def test_subsidy_reduces_capex_and_payback():
    """启用补贴后 ΔCAPEX 线性抵减、回收期缩短，能耗与减排量不变。"""
    common = dict(
        vehicle_type="轻型柴油货车",
        replace_count=1,
        annual_km=35000,
        annual_co2_reduction_t=2.6573,
    )
    base = calculate_single_vehicle_tco(**common)
    subsidised = calculate_single_vehicle_tco(
        **common,
        econ_params=TCOEconomicParameters(scrappage_subsidy_yuan_per_vehicle=35000),
    )

    assert subsidised.delta_capex_per_vehicle_yuan == pytest.approx(
        base.delta_capex_per_vehicle_yuan - 35000, abs=1.0
    )
    assert 0 < subsidised.payback_period_years < base.payback_period_years
    assert subsidised.annual_opex_saving_total_yuan == pytest.approx(
        base.annual_opex_saving_total_yuan, abs=1.0
    )
    assert subsidised.annual_co2_reduction_t == pytest.approx(base.annual_co2_reduction_t)
    assert "交规划发〔2025〕17号" in subsidised.policy_subsidy_note


def test_subsidy_cap_at_zero_capex():
    """补贴超过投资增量时 ΔCAPEX 按 0 计，不产生负投资。"""
    res = calculate_single_vehicle_tco(
        vehicle_type="轻型柴油货车",
        replace_count=1,
        annual_km=35000,
        annual_co2_reduction_t=2.6573,
        econ_params=TCOEconomicParameters(scrappage_subsidy_yuan_per_vehicle=10_000_000),
    )
    assert res.delta_capex_per_vehicle_yuan == 0.0
    assert res.payback_period_years == 0.0
    assert "按 0 计" in res.policy_subsidy_note


def test_schedule_lookup_and_combined_cap():
    """分档表与合计上限自洽：报废 4.5 万 + 新购新能源重卡 9.5 万 ≈ 合计上限 14 万。"""
    assert lookup_scrappage_subsidy("重型柴油货车") == 95000.0
    assert lookup_scrappage_subsidy("中型柴油货车") == 35000.0
    assert lookup_scrappage_subsidy("轻型柴油货车") is None
    assert SCRAPPAGE_SUBSIDY_SCHEDULE["仅报废"]["重型货车"] == 45000
    combined = SCRAPPAGE_SUBSIDY_COMBINED_CAP["报废并新购新能源"]["重型货车"]
    assert combined == (
        SCRAPPAGE_SUBSIDY_SCHEDULE["仅报废"]["重型货车"]
        + SCRAPPAGE_SUBSIDY_SCHEDULE["报废并新购新能源"]["重型货车"]
    )
