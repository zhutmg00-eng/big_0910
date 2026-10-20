"""物流企业模拟碳预算差额估算。

预算计算公式：
    B = Σ (n_i × EF_i × d_reference_i / 1000 × (1 - r_target))
    Gap = E - B

B 仅用于科研原型的减排情景对标，不是法定碳配额。物流运输行业目前
未纳入全国碳市场配额管理，因此差额不代表履约义务或可交易资产。

口径提示（重要）：B 使用的是 CSV 中的**参考年均里程** d_reference，
而 E 使用的是用户填报的**实际里程**。两者不同源，因此当实际里程偏离
参考里程时，Gap 中会混入“活动水平差异”而不只是减排目标差异——
例如顺丰真实车队重卡实际 105000 km/年、参考值 80000 km/年，差额会被
高估约 1.5 倍。``quota_caliber_note()`` 提供相同的口径说明供 UI 展示。
"""
from dataclasses import dataclass

from src.engine.emission_factors import get_all_factors

# ============================================================
# 模拟碳预算基准值（tCO2e/辆/年）
#
# 以下是项目自定义的10%直接运营减排目标情景，不是政策目标或官方配额。
# 每个值都由当前排放因子和CSV中的参考年均里程直接计算，便于复算和
# 敏感性分析，不再使用无法由注释公式复现的手工常数。
# ============================================================
DEFAULT_SCENARIO_REDUCTION_TARGET = 0.10


def build_simulation_budget_benchmarks(
    reduction_target: float = DEFAULT_SCENARIO_REDUCTION_TARGET,
) -> dict[str, float]:
    """按统一公式生成每辆车的模拟预算基准。"""
    if not 0 <= reduction_target < 1:
        raise ValueError("情景减排目标必须在0（含）到1（不含）之间")

    benchmarks = {}
    for vehicle_type, factor in get_all_factors().items():
        annual_km = factor.get("avg_annual_km")
        if annual_km is None or annual_km <= 0:
            raise ValueError(f"车型缺少有效参考年均里程: {vehicle_type}")
        reference_emission = factor["co2_kg_per_km"] * annual_km / 1000
        # 保留内部精度；仅在最终展示/响应时四舍五入，避免车队规模放大
        # 单车基准的舍入误差。
        benchmarks[vehicle_type] = reference_emission * (1 - reduction_target)
    return benchmarks


SIMULATION_BUDGET_BENCHMARK = build_simulation_budget_benchmarks()
# 兼容既有导入；该名称不表示法定配额。
QUOTA_BENCHMARK = SIMULATION_BUDGET_BENCHMARK


@dataclass
class QuotaGapResult:
    """模拟碳预算差额结果（保留旧字段名以兼容现有计算代码）。"""

    total_quota_t: float       # 模拟碳预算总量 (tCO2e)
    total_emission_t: float    # 直接运营排放 (tCO2e)
    gap_t: float               # 差额（正=超出预算，负=低于预算）
    gap_status: str            # "超出预算" | "低于预算" | "基本平衡"
    quota_by_type: dict        # 分车型模拟预算明细
    reduction_target: float    # 项目设定的直接运营减排目标
    # 活动水平口径诊断（见模块 docstring）：预算按参考里程、排放按实际里程，
    # 两者偏离时差额会混入活动水平差异。默认不启用，旧调用方行为不变。
    activity_mismatch_pct: float = 0.0   # 加权平均（实际里程/参考里程 - 1）×100
    caliber_note: str = ""               # 面向用户的口径说明，空表示口径一致


def compute_activity_mismatch(fleet_groups) -> tuple[float, str]:
    """比较车队实际里程与 CSV 参考里程，返回加权偏离百分比与口径说明。

    Args:
        fleet_groups: VehicleGroup 序列（需含 vehicle_type / count / annual_km）

    Returns:
        (mismatch_pct, note)。mismatch_pct 为按活动量（车公里）加权的
        (实际总里程 - 参考总里程) / 参考总里程；note 为空串表示偏差可忽略。
    """
    factors = get_all_factors()
    weighted_actual = 0.0
    weighted_reference = 0.0
    worst = None
    for g in fleet_groups or []:
        ref = (factors.get(g.vehicle_type) or {}).get("avg_annual_km")
        if not ref or ref <= 0:
            continue
        weighted_actual += g.annual_km * g.count
        weighted_reference += ref * g.count
        dev = (g.annual_km - ref) / ref
        if worst is None or abs(dev) > abs(worst[1]):
            worst = (g.vehicle_type, dev, g.annual_km, ref)
    if weighted_reference <= 0:
        return 0.0, ""
    pct = round((weighted_actual / weighted_reference - 1) * 100, 1)
    if abs(pct) < 5.0:
        return pct, ""
    note = (
        f"本车队的填报年均里程与政策基准参考里程整体相差 {pct:+.1f}%"
        f"（最大偏差：{worst[0]} 实际 {worst[2]:,.0f} km/年 vs 参考 {worst[3]:,.0f} km/年）。"
        "模拟碳预算按参考里程计算、排放按填报里程计算，"
        "因此差额中同时包含活动水平差异与减排目标差异，不宜直接解读为纯减排责任。"
    )
    return pct, note


def estimate_quota_gap(
    emission_total: float,
    fleet_summary: dict,
    reduction_target: float = DEFAULT_SCENARIO_REDUCTION_TARGET,
    fleet_groups=None,
) -> QuotaGapResult:
    """
    估算企业直接运营排放与模拟碳预算的差额。

    Args:
        emission_total: 企业年度直接运营排放基线 (tCO2e)
        fleet_summary: 各车型车辆数 {"重型柴油货车": 50, "中型柴油货车": 30, ...}
        reduction_target: 相对参考活动排放的项目情景减排比例
        fleet_groups: 可选，VehicleGroup 序列。传入后启用活动水平口径诊断，
            在 actual/reference 里程偏离超过 5% 时填充 caliber_note。

    Returns:
        QuotaGapResult: 模拟碳预算差额结果

    Note:
        基准值为原型验证用估算值，非官方数据，也不构成履约依据。
    """
    total_quota = 0.0
    quota_by_type = {}
    benchmarks = build_simulation_budget_benchmarks(reduction_target)

    for vtype, count in fleet_summary.items():
        if vtype not in benchmarks:
            raise ValueError(f"车型没有模拟预算基准: {vtype}")
        benchmark = benchmarks[vtype]
        type_quota = count * benchmark
        total_quota += type_quota
        quota_by_type[vtype] = {
            "车辆数": count,
            "基准值_t_per_辆": round(benchmark, 4),
            "模拟预算_t": round(type_quota, 2),
        }

    gap = emission_total - total_quota

    if (emission_total <= 0 and total_quota <= 0) or abs(gap) < max(emission_total * 0.01, 1e-6):
        status = "基本平衡"
    elif gap > 0:
        status = "超出预算"
    else:
        status = "低于预算"

    mismatch_pct, caliber_note = (0.0, "")
    if fleet_groups:
        mismatch_pct, caliber_note = compute_activity_mismatch(fleet_groups)

    return QuotaGapResult(
        total_quota_t=round(total_quota, 2),
        total_emission_t=round(emission_total, 2),
        gap_t=round(gap, 2),
        gap_status=status,
        quota_by_type=quota_by_type,
        reduction_target=reduction_target,
        activity_mismatch_pct=mismatch_pct,
        caliber_note=caliber_note,
    )
