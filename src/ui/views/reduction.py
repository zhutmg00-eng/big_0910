"""Reduction-scenario configuration and results."""

from __future__ import annotations

import logging

import streamlit as st

from src.ui.components.charts import plot_reduction_comparison, plot_tco_payback_curve, plot_tco_cost_breakdown
from src.ui.navigation import navigate_to
from src.ui.theme import empty_state, notice, page_header


logger = logging.getLogger(__name__)


def render_reduction() -> None:
    page_header(
        "分析 · 第二步",
        "减排情景分析",
        "选择目标车型，组合新能源替换与满载率提升措施，比较直接运营排放及碳价对标成本变化。",
    )
    carbon_result = st.session_state.get("carbon_result")
    fleet_data = st.session_state.get("fleet_data", [])
    if not carbon_result or not fleet_data:
        empty_state("缺少排放基线", "先在排放盘点中录入车队并完成计算，再配置减排措施。")
        st.button(
            "前往排放盘点",
            type="primary",
            on_click=navigate_to,
            args=("排放盘点",),
        )
        return

    _render_baseline(carbon_result)
    st.markdown("## 配置措施")

    emission_by_type = carbon_result.get("emission_by_type", {})
    vehicle_types = list(emission_by_type)
    selected_type = st.selectbox("目标车型", vehicle_types)
    type_info = emission_by_type.get(selected_type, {})
    type_count = int(type_info.get("车辆数", 0))

    current_load = next(
        (
            float(item.get("load_factor", 0.75))
            for item in fleet_data
            if item["vehicle_type"] == selected_type
        ),
        0.75,
    )
    c1, c2 = st.columns(2)
    replace_count = c1.slider(
        "替换为新能源车（辆）",
        min_value=0,
        max_value=type_count,
        value=0,
        step=1,
        help="新能源车直接运营排放按零计，未计购电间接排放。",
    )
    replace_load = c2.slider(
        "提升满载率（辆）",
        min_value=0,
        max_value=type_count,
        value=0,
        step=1,
        help="同一车辆不同时计入新能源替换和满载率提升。",
    )
    target_load_pct = st.slider(
        "目标满载率",
        min_value=50,
        max_value=100,
        value=int(round(max(current_load, 0.80) * 100)),
        step=5,
        format="%d%%",
    )
    target_load = target_load_pct / 100

    invalid_overlap = replace_count + replace_load > type_count
    if invalid_overlap:
        st.error(f"两项措施合计涉及 {replace_count + replace_load} 辆，超过该车型的 {type_count} 辆。")
    elif replace_load > 0 and target_load <= current_load:
        st.warning("目标满载率需高于当前满载率，才能形成减排情景。")

    if st.button(
        "计算减排情景",
        type="primary",
        width="stretch",
        disabled=invalid_overlap,
    ):
        if replace_count == 0 and replace_load == 0:
            st.warning("至少配置一项减排措施后再计算。")
        elif replace_load > 0 and target_load <= current_load:
            st.warning("请提高目标满载率后再计算。")
        else:
            _calculate_reduction(
                carbon_result,
                fleet_data,
                selected_type,
                replace_count,
                replace_load,
                target_load,
            )

    scenario = st.session_state.get("reduction_result")
    if scenario:
        _render_scenario(scenario)


def _render_baseline(carbon_result: dict) -> None:
    budget = carbon_result.get("carbon_budget", {})
    st.markdown("## 当前基线")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("直接运营排放", f"{carbon_result.get('total_emission_t', 0):,.0f} tCO2e")
    m2.metric("车队规模", f"{carbon_result.get('total_vehicles', 0):,} 辆")
    m3.metric("预算差额", f"{budget.get('预算差额_t', 0):+,.0f} tCO2e")
    m4.metric("情景状态", budget.get("状态", "未知"))

    # 与总览页保持一致的口径警示：预算差额混有活动水平差异时，减排情景的
    # "消除超出量"结论也会被同比例放大，必须先提示。
    _mismatch_pct = budget.get("活动水平偏离_pct") or 0
    if abs(_mismatch_pct) >= 5:
        st.warning(
            f"基线里程偏离参考值 **{_mismatch_pct:+.1f}%**，预算差额中混入活动水平差异，"
            f"下面各情景的「超出量」会被同比例放大，请勿直接当作减排目标缺口。"
        )


def _calculate_reduction(
    carbon_result: dict,
    fleet_data: list[dict],
    selected_type: str,
    replace_count: int,
    replace_load: int,
    target_load: float,
) -> None:
    with st.spinner("正在计算减排情景…"):
        try:
            from src.engine.calculator import VehicleGroupData
            from src.engine.reduction import analyze_reduction_scenario

            # The engine applies measures in fleet order. Put the selected type first
            # so both measures stay within the target group validated by the UI.
            ordered_fleet = sorted(
                fleet_data,
                key=lambda item: item["vehicle_type"] != selected_type,
            )
            baseline_fleet = [
                VehicleGroupData(
                    vehicle_type=item["vehicle_type"],
                    count=item["count"],
                    annual_km=item["annual_km"],
                    load_factor=item["load_factor"],
                )
                for item in ordered_fleet
            ]
            changes = {}
            if replace_count:
                changes["替换为新能源物流车"] = replace_count
            if replace_load:
                changes[f"提升满载率至{target_load}"] = replace_load

            scenario = analyze_reduction_scenario(
                baseline_fleet=baseline_fleet,
                changes=changes,
                budget_reduction_target=carbon_result.get("carbon_budget", {}).get(
                    "情景减排目标", 0.10
                ),
            ).to_dict()
            scenario["selected_type"] = selected_type
            scenario["replace_count"] = replace_count
            scenario["replace_load"] = replace_load
            scenario["target_load"] = target_load
            st.session_state.reduction_result = scenario
        except Exception:
            logger.exception("计算减排情景失败")
            st.error("减排情景计算失败，请检查输入或稍后重试。")


def _render_scenario(scenario: dict) -> None:
    st.divider()
    st.markdown("## 减排与环保账")
    savings = scenario.get("cost_savings", {})
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("情景直接排放", f"{scenario.get('scenario_emission', 0):,.0f} tCO2e")
    m2.metric("直接减排量", f"{scenario.get('reduction_t', 0):,.0f} tCO2e")
    m3.metric("减排比例", f"{scenario.get('reduction_pct', 0):.1f}%")
    m4.metric("情景成本变化", f"{savings.get('节省_元', 0):,.0f} 元")

    st.plotly_chart(
        plot_reduction_comparison(
            scenario.get("baseline_emission", 0),
            scenario.get("scenario_emission", 0),
        ),
        width="stretch",
        config={"displayModeBar": False, "responsive": True},
    )

    # TCO 投资经济账与投资回收期模块
    tco = scenario.get("tco_analysis")
    if tco and tco.get("total_replace_count", 0) > 0:
        st.markdown("## 💰 TCO 投资经济账与投资回收期（Payback Period）")
        st.caption("全生命周期综合成本模型：TCO = CAPEX（购置+充电）+ OPEX（能耗+维保）- 残值")

        tc1, tc2, tc3, tc4 = st.columns(4)
        tc1.metric(
            "初始增量投资 (ΔCAPEX)",
            f"{tco.get('total_delta_capex_wan', 0):,.1f} 万元",
            help="包含新能源车购车差额与充电桩配套分摊",
        )
        tc2.metric(
            "年运营节省 (ΔOPEX)",
            f"{tco.get('total_annual_opex_saving_wan', 0):,.1f} 万元/年",
            help="燃油费节省 - 充电电费 + 年均维保节省",
        )
        payback = tco.get("overall_payback_period_years")
        payback_str = f"{payback:.1f} 年" if payback is not None else "无法回本"
        tc3.metric(
            "静态投资回收期",
            payback_str,
            help="ΔCAPEX / ΔOPEX，代表多少年可通过运营节省收回购车增量成本",
        )
        mac = tco.get("overall_mac_yuan_per_tco2e")
        mac_str = f"{mac:+.1f} 元/t" if mac is not None else "N/A"
        tc4.metric(
            "吨碳减排边际成本 (MAC)",
            mac_str,
            help="单位吨碳减排边际成本。负值代表全生命周期不仅减排，还能产生净经济收益",
        )

        c1, c2 = st.columns(2)
        with c1:
            st.plotly_chart(
                plot_tco_payback_curve(
                    tco.get("yearly_cashflow", []),
                    payback,
                ),
                width="stretch",
                config={"displayModeBar": False, "responsive": True},
            )
        with c2:
            single_tco_map = tco.get("by_vehicle_type", {})
            vtype = scenario.get("selected_type", "重型柴油货车")
            single_info = single_tco_map.get(vtype, {})
            km = float(single_info.get("annual_km", 80000.0))
            st.plotly_chart(
                plot_tco_cost_breakdown(
                    vtype,
                    scenario.get("replace_count", 1),
                    km,
                    single_info,
                ),
                width="stretch",
                config={"displayModeBar": False, "responsive": True},
            )

    st.markdown("### 已应用措施")
    applied = []
    if scenario.get("replace_count"):
        applied.append(
            {
                "目标车型": scenario.get("selected_type", ""),
                "措施": "替换为新能源物流车",
                "车辆数": scenario["replace_count"],
            }
        )
    if scenario.get("replace_load"):
        applied.append(
            {
                "目标车型": scenario.get("selected_type", ""),
                "措施": f"满载率提升至 {scenario.get('target_load', 0):.0%}",
                "车辆数": scenario["replace_load"],
            }
        )
    st.table(applied)

    st.markdown("### 模型建议")
    recommendations = scenario.get("recommendations", [])
    if recommendations:
        for index, recommendation in enumerate(recommendations, start=1):
            st.write(f"{index}. {recommendation}")
    else:
        empty_state("暂无进一步建议", "当前情景未生成可用建议，请调整措施后重新计算。")
    notice(
        "解释边界",
        "结果反映直接运营排放变化。新能源替换情景仍需结合当地电网排放因子、购置成本和运营数据做完整评估。",
        amber=True,
    )
