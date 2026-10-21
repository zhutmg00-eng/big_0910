"""Home, inventory, and emission-factor views."""

from __future__ import annotations

import requests
import streamlit as st

from src.ui.api_client import API_BASE_URL, api_post, show_api_error
from src.ui.components.charts import (
    plot_emission_pie,
    plot_quota_comparison,
    plot_uncertainty_contributions,
    plot_uncertainty_histogram,
)
from src.ui.navigation import navigate_to
from src.ui.theme import empty_state, notice, page_header


# 演示用示例车队：干线 + 城配混合结构，便于答辩现场一键复现完整流程
SAMPLE_FLEET = [
    {"vehicle_type": "重型柴油货车", "count": 40, "annual_km": 100000, "load_factor": 0.62},
    {"vehicle_type": "LNG重型货车", "count": 15, "annual_km": 90000, "load_factor": 0.70},
    {"vehicle_type": "中型柴油货车", "count": 30, "annual_km": 50000, "load_factor": 0.68},
    {"vehicle_type": "轻型柴油货车", "count": 60, "annual_km": 35000, "load_factor": 0.55},
    {"vehicle_type": "新能源物流车", "count": 25, "annual_km": 30000, "load_factor": 0.60},
]

VEHICLE_TYPES = [
    "重型柴油货车",
    "中型柴油货车",
    "轻型柴油货车",
    "微型汽油货车",
    "LNG重型货车",
    "新能源物流车",
]


def render_home() -> None:
    page_header(
        "项目总览",
        "把车队数据转化为可复核的减排判断",
        "从排放基线开始，比较减排情景，再将核算结果与政策依据整理为报告。",
    )

    fleet = st.session_state.get("fleet_data", [])
    result = st.session_state.get("carbon_result")
    report_path = st.session_state.get("report_path")

    m1, m2, m3 = st.columns(3)
    m1.metric("车队记录", f"{len(fleet)} 组", help="已录入的车型配置数量")
    m2.metric(
        "最近核算",
        f"{result.get('total_emission_t', 0):,.0f} tCO2e" if result else "待计算",
        help="车辆直接运营排放",
    )
    m3.metric("报告状态", "已生成" if report_path else "未生成")

    st.markdown("## 建议工作流")
    st.markdown(
        """
        <div class="workflow-strip" role="list" aria-label="项目分析流程">
            <div class="workflow-step" role="listitem">
                <span class="workflow-step__number">01</span>
                <strong>建立排放基线</strong>
                <span>录入车型、数量、里程和满载率，形成可复核盘点。</span>
            </div>
            <div class="workflow-step" role="listitem">
                <span class="workflow-step__number">02</span>
                <strong>比较减排情景</strong>
                <span>调整新能源替换与满载率，查看排放和成本变化。</span>
            </div>
            <div class="workflow-step" role="listitem">
                <span class="workflow-step__number">03</span>
                <strong>整理依据并导出</strong>
                <span>检索政策资料，将核算口径、结果和建议写入报告。</span>
            </div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    c1, c2, c3 = st.columns(3)
    c1.button(
        "开始排放盘点",
        type="primary",
        width="stretch",
        on_click=navigate_to,
        args=("排放盘点",),
    )
    c2.button(
        "进入减排分析",
        width="stretch",
        disabled=not bool(result),
        on_click=navigate_to,
        args=("减排分析",),
    )
    c3.button(
        "查看报告导出",
        width="stretch",
        disabled=not bool(result),
        on_click=navigate_to,
        args=("报告导出",),
    )

    notice(
        "科研原型边界",
        "物流运输行业目前未纳入全国碳市场配额管理。模拟碳预算用于方案比较，不代表法定配额、履约义务或可交易资产。",
        amber=True,
    )


def render_inventory() -> None:
    page_header(
        "核算 · 第一步",
        "车队直接运营排放盘点",
        "录入年度车队活动数据，计算分车型排放、模拟碳预算差额和碳价对标情景。",
    )
    st.session_state.setdefault("fleet_data", [])

    company_name = st.text_input(
        "企业名称",
        value=st.session_state.get("company_name", "示例物流公司"),
        key="inventory_company",
        # 后端 CompanyInfo.company_name 限制 100 字符；这里不设上限时，
        # 超长名称要到点击计算后才由 422 拦下，用户事先无从得知。
        max_chars=100,
        help="最多 100 个字符，会显示在导出的 PDF 报告抬头。",
    )
    scenario_reduction_target_pct = st.slider(
        "模拟预算减排目标",
        min_value=0,
        max_value=50,
        value=int(round(float(st.session_state.get("scenario_reduction_target", 0.10)) * 100)),
        step=5,
        format="%d%%",
        help="相对各车型参考活动排放的科研情景参数，不是政策目标或法定配额。",
    )
    scenario_reduction_target = scenario_reduction_target_pct / 100

    st.markdown("## 添加车队记录")
    with st.form("fleet_entry", clear_on_submit=False):
        c1, c2 = st.columns(2)
        vehicle_type = c1.selectbox("车型", VEHICLE_TYPES)
        count = c2.number_input("车辆数量（辆）", min_value=1, value=50, step=1)
        c3, c4 = st.columns(2)
        annual_km = c3.number_input("单车年均里程（km）", min_value=1000, value=80000, step=1000)
        load_factor_pct = c4.slider("平均满载率", 0, 100, 75, 5, format="%d%%")
        add_vehicle = st.form_submit_button("添加到车队", type="primary")

    if not st.session_state.fleet_data:
        if st.button("载入示例车队（5 类车型 · 170 辆）", help="用于演示完整流程，可随后修改或删除"):
            st.session_state.fleet_data = [dict(x) for x in SAMPLE_FLEET]
            st.session_state.company_name = "示例物流公司"
            st.rerun()

    if add_vehicle:
        st.session_state.fleet_data.append(
            {
                "vehicle_type": vehicle_type,
                "count": int(count),
                "annual_km": int(annual_km),
                "load_factor": load_factor_pct / 100,
            }
        )
        st.session_state.pop("carbon_result", None)
        st.session_state.pop("reduction_result", None)
        st.session_state.pop("report_path", None)
        st.session_state.pop("uncertainty_result", None)
        st.rerun()

    fleet = st.session_state.fleet_data
    st.markdown("## 当前车队")
    if fleet:
        rows = [
            {
                "序号": index + 1,
                "车型": item["vehicle_type"],
                "车辆数": item["count"],
                "年均里程（km）": f"{item['annual_km']:,}",
                "满载率": f"{item['load_factor']:.0%}",
            }
            for index, item in enumerate(fleet)
        ]
        st.dataframe(rows, width="stretch", hide_index=True)

        d1, d2 = st.columns([3, 1])
        selected_row = d1.selectbox(
            "需要删除的记录",
            range(len(fleet)),
            format_func=lambda i: f"{i + 1}. {fleet[i]['vehicle_type']} · {fleet[i]['count']} 辆",
        )
        if d2.button("删除所选", width="stretch"):
            fleet.pop(selected_row)
            st.session_state.pop("carbon_result", None)
            st.session_state.pop("reduction_result", None)
            st.session_state.pop("report_path", None)
            st.session_state.pop("uncertainty_result", None)
            st.rerun()

        if st.button("计算排放基线", type="primary", width="stretch"):
            if not company_name.strip():
                st.error("请填写企业名称后再计算。")
            else:
                _calculate_inventory(company_name, scenario_reduction_target)
    else:
        empty_state("尚未添加车队记录", "先填写上方四项活动数据并添加记录，至少需要一组车型才能计算。")

    result = st.session_state.get("carbon_result")
    if result:
        _render_inventory_result(result)


def _calculate_inventory(company_name: str, reduction_target: float) -> None:
    with st.spinner("正在核算车队排放…"):
        try:
            response = api_post(
                "/api/calculate",
                {
                    "company_name": company_name.strip(),
                    "fleet": st.session_state.fleet_data,
                    "scenario_reduction_target": reduction_target,
                },
            )
            if response.status_code != 200:
                show_api_error(response)
                return
            st.session_state.carbon_result = response.json()
            st.session_state.company_name = company_name.strip()
            st.session_state.scenario_reduction_target = reduction_target
            st.session_state.pop("reduction_result", None)
            st.session_state.pop("report_path", None)
        except requests.RequestException as exc:
            st.error(f"无法连接核算服务（{API_BASE_URL}）：{exc}")


def _render_inventory_result(result: dict) -> None:
    budget = result.get("carbon_budget", {})
    gap = budget.get("预算差额_t", 0)
    status = budget.get("状态", "未知")

    st.divider()
    st.markdown("## 核算结果")
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("直接运营排放", f"{result.get('total_emission_t', 0):,.0f} tCO2e")
    m2.metric("模拟碳预算", f"{budget.get('模拟碳预算_t', 0):,.0f} tCO2e")
    m3.metric("预算差额", f"{gap:+,.0f} tCO2e")
    m4.metric("情景状态", status)

    # 口径警示：B 按 CSV 参考里程算、E 按用户填报实际里程算，两者不同源。
    # 里程偏离较大时 Gap 里混入了"活动水平差异"，不是纯减排目标缺口。
    # API 已在 carbon_budget["活动水平偏离_pct"] 里算好，这里必须让用户看见。
    _mismatch_pct = budget.get("活动水平偏离_pct") or 0
    if abs(_mismatch_pct) >= 5:
        st.warning(
            f"**口径提示（影响预算差额的可比性）**\n\n"
            f"模拟碳预算按政策参考年均里程计算，直接运营排放按你填报的**实际里程**计算，"
            f"本次两者偏离 **{_mismatch_pct:+.1f}%**。\n\n"
            f"因此上面的预算差额里混入了活动水平差异：实际里程高于参考值时，"
            f"差额会被系统性高估。做同比或跨企业对比前请先统一下里程口径，"
            f"或参阅报告中的分车型基准值自行换算。"
        )

    chart_left, chart_right = st.columns([1, 1.25])
    with chart_left:
        st.plotly_chart(
            plot_emission_pie(result.get("emission_by_type", {})),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )
    with chart_right:
        st.plotly_chart(
            plot_quota_comparison(
                result.get("total_emission_t", 0),
                budget.get("模拟碳预算_t", 0),
                gap,
            ),
            width="stretch",
            config={"displayModeBar": False, "responsive": True},
        )

    st.markdown("### 分车型明细")
    emission_rows = [
        {"车型": name, **details}
        for name, details in result.get("emission_by_type", {}).items()
    ]
    st.dataframe(emission_rows, width="stretch", hide_index=True)

    _render_uncertainty_section()

    st.markdown("### 碳价对标情景")
    cost = result.get("scenario_cost", {})
    if cost.get("情景成本_参考价") is not None:
        cost_rows = [
            {"项目": "参考碳价", "数值": f"{cost.get('当前碳价_元每吨', 0):,.2f} 元/tCO2e"},
            {"项目": "情景成本参考值", "数值": f"{cost.get('情景成本_参考价', 0):,.0f} 元"},
            {
                "项目": "情景成本区间",
                "数值": (
                    f"{cost.get('情景成本区间_low', 0):,.0f} – "
                    f"{cost.get('情景成本区间_high', 0):,.0f} 元"
                ),
            },
        ]
    else:
        cost_rows = [
            {"项目": "情景判断", "数值": cost.get("情景判断", status)},
            {"项目": "预算结余", "数值": f"{cost.get('预算结余_t', abs(gap)):,.0f} tCO2e"},
            {
                "项目": "对标潜在价值区间",
                "数值": f"{cost.get('潜在价值_low', 0):,.0f} – {cost.get('潜在价值_high', 0):,.0f} 元",
            },
        ]
    st.table(cost_rows)
    if cost.get("is_fallback_price"):
        st.warning(
            f"⚠️ 碳价数据不可用，当前使用{cost.get('碳价数据来源', '模拟参考价')}。"
            "该结果不能作为实测碳价结论引用，请先恢复 data/raw/carbon_price_history.csv。"
        )
    st.caption(f"碳价数据来源：{cost.get('碳价数据来源', '未标注')}")
    notice("口径提示", cost.get("备注", result.get("methodology_note", "科研情景估算，仅供方案比较。")), amber=True)


def _render_uncertainty_section() -> None:
    st.markdown("### 不确定性分析")
    st.caption(
        "点估计掩盖了排放因子的多来源差异与活动数据误差。按 IPCC 2006 Approach 2 做蒙特卡洛抽样，"
        "给出 90% 置信区间，并指出哪项数据最值得优先改进。"
    )
    c1, c2, c3 = st.columns([1.2, 1, 1])
    quality = c1.radio(
        "活动数据质量", ["台账", "抽样", "估计"], index=1, horizontal=True,
        help="台账/GPS：里程 CV 5%；抽样统计：CV 10%；经验估计：CV 20%",
    )
    n_samples = c2.select_slider("抽样次数", options=[2000, 5000, 10000, 20000], value=10000)
    run = c3.button("运行蒙特卡洛", width="stretch")
    if run:
        try:
            resp = api_post("/api/uncertainty", {
                "fleet": st.session_state.fleet_data, "n_samples": n_samples, "data_quality": quality,
            })
            if resp.status_code != 200:
                show_api_error(resp)
            else:
                st.session_state.uncertainty_result = resp.json()
        except requests.RequestException as exc:
            st.error(f"无法连接核算服务（{API_BASE_URL}）：{exc}")

    u = st.session_state.get("uncertainty_result")
    if not u:
        return
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("点估计", f"{u['point_estimate_t']:,.0f} t")
    m2.metric("P50 中位数", f"{u['p50_t']:,.0f} t")
    m3.metric("90% 区间", f"{u['p5_t']:,.0f} – {u['p95_t']:,.0f}")
    m4.metric("相对不确定度", f"±{u['relative_uncertainty_pct']:.1f}%")
    left, right = st.columns(2)
    with left:
        st.plotly_chart(
            plot_uncertainty_histogram(u["histogram"], u["point_estimate_t"], u["p5_t"], u["p95_t"]),
            width="stretch", config={"displayModeBar": False},
        )
    with right:
        st.plotly_chart(plot_uncertainty_contributions(u["contributions"]), width="stretch",
                        config={"displayModeBar": False})
    top = next(iter(u["contributions"]), None)
    if top:
        bias = (u["mean_t"] - u["point_estimate_t"]) / u["point_estimate_t"] * 100 if u["point_estimate_t"] else 0
        tip = f"最大不确定性来源是「{top}」，优先用台账或 GPS 数据替换该项估计值，区间收窄最明显。"
        if abs(bias) >= 1:
            tip += f" 抽样均值较点估计{'偏高' if bias > 0 else '偏低'} {abs(bias):.1f}%，说明因子分布不对称（如 LNG 实测值普遍高于指南值）。"
        notice("解读", tip)
    with st.expander("排放因子抽样分布（三角分布参数）"):
        st.dataframe(
            [{"车型": k, "分布": v["dist"], "下限": v["low"], "众数(基准)": v["mode"], "上限": v["high"],
              "来源数": v["n_sources"]} for k, v in u["ef_distributions"].items()],
            hide_index=True, width="stretch",
        )


def render_factors() -> None:
    page_header(
        "方法与数据",
        "排放因子参考表",
        "查看当前模型使用的车型排放因子、活动水平参考值和数据来源。",
    )
    from src.engine.emission_factors import get_all_factors

    factors = get_all_factors()
    rows = [
        {
            "车型": name,
            "燃料类型": data["fuel_type"],
            "CO2 排放因子（kg/km）": data["co2_kg_per_km"],
            "油耗参考（L/100km）": data.get("fuel_consumption_l_per_100km") or "不适用",
            "年均里程参考（km）": f"{data['avg_annual_km']:,}",
        }
        for name, data in factors.items()
    ]
    st.dataframe(rows, width="stretch", hide_index=True)

    st.markdown("## 数据来源")
    for name, data in factors.items():
        with st.expander(name):
            st.write(data["source"])
    notice(
        "使用建议",
        "参考因子适合科研原型和前期情景比较。企业正式盘查应优先使用可追溯的燃料消耗、里程和采购台账。",
    )
