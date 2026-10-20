"""口径诊断：碳价回退标注、预算活动水平偏离、成本口径一致性。

这些测试锁定的是“输出必须可区分真伪”这一约束：当底层数据缺失或口径
不一致时，结果里必须留下可追溯的标记，而不是静默给出一组看起来正常的数字。
"""
from __future__ import annotations

import pandas as pd
import pytest

from src.engine.calculator import VehicleGroupData, calculate_emission
from src.engine.carbon_price import (
    carbon_price_data_available,
    estimate_compliance_cost,
    load_carbon_price_data,
    price_window_stats,
)
from src.engine.quota import (
    build_simulation_budget_benchmarks,
    compute_activity_mismatch,
    estimate_quota_gap,
)


# ============================================================
# 碳价：回退必须显式标注
# ============================================================

def test_real_price_data_has_no_fallback_flag():
    df = load_carbon_price_data()
    if df is None:  # 数据文件缺失时本测试无意义
        pytest.skip("碳价原始数据不可用")
    cost = estimate_compliance_cost(100.0, df)
    assert cost["is_fallback_price"] is False
    assert "仅真实成交" in cost["碳价数据来源"]


def test_missing_price_data_is_flagged_as_fallback():
    cost = estimate_compliance_cost(100.0, None)
    assert cost["is_fallback_price"] is True
    assert "模拟参考价" in cost["碳价数据来源"]
    # 硬编码参考价仍是 70 元/吨，但必须能被识别出来
    assert cost["情景成本_参考价"] == pytest.approx(7000.0)


def test_fallback_available_helper_matches_loader():
    assert carbon_price_data_available() == (load_carbon_price_data() is not None)


def test_window_current_lies_inside_min_max():
    """current 与 mean/min/max 必须同源，否则出现“参考价不在区间内”。"""
    df = pd.DataFrame({
        "日期": pd.to_datetime([
            "2026-08-01", "2026-08-02", "2026-08-03", "2026-09-01",
        ]),
        "收盘价": [90.0, 95.0, 92.0, 87.0],
        # 末行为插值：旧实现会把 current 取成 87.0，落在 90~95 的真实成交区间之外
        "数据来源": ["真实数据", "真实数据", "真实数据", "插值数据"],
    })
    w = price_window_stats(df, days=90)
    assert w["min"] <= w["current"] <= w["max"], w
    assert w["current"] == 92.0
    assert w["n_obs"] == 3


def test_window_falls_back_to_all_rows_without_source_column():
    df = pd.DataFrame({
        "日期": pd.to_datetime(["2026-08-01", "2026-08-05"]),
        "收盘价": [80.0, 84.0],
    })
    w = price_window_stats(df)
    assert w["current"] == 84.0
    assert w["mean"] == 82.0


# ============================================================
# 模拟碳预算：活动水平偏离必须可诊断
# ============================================================

def test_activity_mismatch_weighted_by_activity_volume():
    groups = [
        VehicleGroupData(vehicle_type="重型柴油货车", count=10, annual_km=160000, load_factor=0.8),
        VehicleGroupData(vehicle_type="轻型柴油货车", count=10, annual_km=30000, load_factor=0.8),
    ]
    pct, note = compute_activity_mismatch(groups)
    # 实际里程 10×160000 + 10×30000 = 1,900,000 km
    # 参考里程 10×80000  + 10×30000 = 1,100,000 km
    # 按活动量加权（而非车辆数等权）→ +72.7%，更贴近预算总量被放大的真实幅度
    assert pct == pytest.approx(72.7, abs=0.1)
    assert note


def test_activity_mismatch_is_silent_when_within_tolerance():
    groups = [VehicleGroupData("重型柴油货车", 10, 82000, 0.8)]  # 参考 80000，偏离 +2.5%
    pct, note = compute_activity_mismatch(groups)
    assert abs(pct) < 5.0
    assert note == ""


def test_gap_result_carries_caliber_note_for_deviating_fleet():
    groups = [VehicleGroupData("重型柴油货车", 50, 135000, 0.85)]
    summary = {"重型柴油货车": 50}
    emission = calculate_emission(groups).total_emission_t
    gap = estimate_quota_gap(emission, summary, 0.10, fleet_groups=groups)
    assert gap.activity_mismatch_pct > 5.0
    assert "参考里程" in gap.caliber_note


def test_gap_result_without_fleet_groups_keeps_legacy_behaviour():
    """不传 fleet_groups 时行为与旧版完全一致，不影响既有调用方。"""
    result = estimate_quota_gap(4000.0, {"重型柴油货车": 50})
    assert result.gap_t == 842.8
    assert result.gap_status == "超出预算"
    assert result.caliber_note == ""
    assert result.activity_mismatch_pct == 0.0


def test_reference_mileage_budget_is_unchanged():
    """预算口径仍是参考里程，本次改动只做诊断，不改核算定义。"""
    assert build_simulation_budget_benchmarks(0.10)["重型柴油货车"] == pytest.approx(
        0.877 * 80000 / 1000 * 0.90
    )
