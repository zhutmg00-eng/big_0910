"""Plotly charts used across the carbon-analysis interface."""

from __future__ import annotations

from typing import Dict, List, Optional

import plotly.graph_objects as go


INK = "#17231d"
MUTED = "#66756d"
GRID = "#dfe6e2"
GREEN = "#1f6a4a"
GREEN_DARK = "#155239"
TEAL = "#39766c"
AMBER = "#b27425"
RED = "#a83a35"
GRAY = "#8a9891"
CATEGORY_PALETTE = [GREEN, AMBER, TEAL, "#728078", "#4f6259", "#d0a35b"]

TYPE_LABELS: Dict[str, str] = {
    "重型柴油货车": "重型柴油货车",
    "中型柴油货车": "中型柴油货车",
    "轻型柴油货车": "轻型柴油货车",
    "微型汽油货车": "微型汽油货车",
    "LNG重型货车": "LNG重型货车",
    "新能源物流车": "新能源物流车",
}


def _apply_layout(fig: go.Figure, *, title: str, height: int = 400) -> go.Figure:
    fig.update_layout(
        title=dict(text=title, x=0, xanchor="left", font=dict(size=16, color=INK)),
        height=height,
        margin=dict(l=20, r=20, t=58, b=35),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(family="Segoe UI, Microsoft YaHei, sans-serif", color=INK, size=12),
        hoverlabel=dict(bgcolor="#ffffff", bordercolor=GRID, font=dict(color=INK)),
    )
    return fig


def plot_emission_pie(emission_by_type: dict) -> go.Figure:
    """Show each vehicle type's share of direct operating emissions."""
    labels = [TYPE_LABELS.get(name, name) for name in emission_by_type]
    values = [details.get("排放量_tCO2", 0) for details in emission_by_type.values()]
    fig = go.Figure(
        data=[
            go.Pie(
                labels=labels,
                values=values,
                hole=0.62,
                marker=dict(colors=CATEGORY_PALETTE, line=dict(color="#ffffff", width=2)),
                textposition="inside",
                textinfo="percent",
                sort=False,
                hovertemplate="%{label}<br>%{value:,.2f} tCO2e<br>占比 %{percent}<extra></extra>",
            )
        ]
    )
    _apply_layout(fig, title="车型排放构成", height=390)
    fig.update_layout(
        showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=-0.05, xanchor="left", x=0),
        margin=dict(l=10, r=10, t=58, b=80),
    )
    return fig


def plot_quota_comparison(total_emission: float, total_quota: float, gap: float) -> go.Figure:
    """Compare direct emissions with the simulated carbon budget."""
    labels = ["直接运营排放", "模拟碳预算", "预算差额"]
    values = [total_emission, total_quota, gap]
    gap_color = RED if gap > 0 else TEAL
    fig = go.Figure(
        data=[
            go.Bar(
                x=labels,
                y=values,
                marker_color=[GREEN, GRAY, gap_color],
                text=[f"{total_emission:,.1f}", f"{total_quota:,.1f}", f"{gap:+,.1f}"],
                textposition="outside",
                cliponaxis=False,
                hovertemplate="%{x}<br>%{y:,.2f} tCO2e<extra></extra>",
            )
        ]
    )
    _apply_layout(fig, title="排放与模拟预算", height=390)
    fig.update_layout(yaxis_title="tCO2e", showlegend=False)
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=True, zerolinecolor=MUTED)
    fig.update_xaxes(showgrid=False)
    return fig


def plot_reduction_comparison(baseline: float, scenario: float) -> go.Figure:
    """Compare baseline and post-measure direct operating emissions."""
    reduction = max(0.0, baseline - scenario)
    fig = go.Figure(
        data=[
            go.Bar(
                y=["基线", "减排情景"],
                x=[baseline, scenario],
                orientation="h",
                marker_color=[GRAY, GREEN],
                text=[f"{baseline:,.1f} tCO2e", f"{scenario:,.1f} tCO2e"],
                textposition="outside",
                cliponaxis=False,
                hovertemplate="%{y}<br>%{x:,.2f} tCO2e<extra></extra>",
            )
        ]
    )
    _apply_layout(fig, title=f"情景前后对比 · 减少 {reduction:,.1f} tCO2e", height=320)
    fig.update_layout(xaxis_title="tCO2e", showlegend=False, margin=dict(l=20, r=90, t=58, b=40))
    fig.update_xaxes(showgrid=True, gridcolor=GRID, rangemode="tozero")
    fig.update_yaxes(autorange="reversed")
    return fig


def plot_carbon_price_history(df) -> go.Figure:
    """碳价序列：真实成交点（实心）与插值点（空心浅色）分开绘制。"""
    real = df[df["数据来源"] == "真实数据"]
    interp = df[df["数据来源"] != "真实数据"]
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=df["日期"], y=df["收盘价"], mode="lines", name="趋势线（含插值）",
        line=dict(color=GRAY, width=1, dash="dot"), hoverinfo="skip",
    ))
    fig.add_trace(go.Scatter(
        x=interp["日期"], y=interp["收盘价"], mode="markers", name=f"插值点 · {len(interp)}",
        marker=dict(color="rgba(0,0,0,0)", size=5, line=dict(color=AMBER, width=1)),
        hovertemplate="%{x|%Y-%m-%d}<br>插值 %{y:.2f} 元<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=real["日期"], y=real["收盘价"], mode="markers", name=f"真实成交 · {len(real)}",
        marker=dict(color=GREEN, size=7),
        hovertemplate="%{x|%Y-%m-%d}<br>真实 %{y:.2f} 元<extra></extra>",
    ))
    _apply_layout(fig, title="全国碳市场收盘价（真实 vs 插值）", height=340)
    fig.update_layout(yaxis_title="元/tCO2e",
                      legend=dict(orientation="h", yanchor="top", y=-0.12, xanchor="left", x=0))
    return fig


def plot_carbon_price_stats(price_stats: dict) -> go.Figure | None:
    """Show current and recent carbon-price reference points."""
    if not price_stats:
        return None
    points = [
        ("当前价", price_stats.get("当前价"), GREEN),
        ("90 日均价", price_stats.get("近90日均价"), GRAY),
        ("90 日最高", price_stats.get("近90日最高"), RED),
        ("90 日最低", price_stats.get("近90日最低"), AMBER),
    ]
    points = [(label, value, color) for label, value, color in points if value is not None]
    if not points:
        return None

    fig = go.Figure()
    for label, value, color in points:
        fig.add_trace(
            go.Scatter(
                x=[0, 1],
                y=[value, value],
                mode="lines",
                name=f"{label} · {value:.2f} 元",
                line=dict(color=color, width=2, dash="dot" if label != "当前价" else "solid"),
                hovertemplate=f"{label}<br>{value:.2f} 元/tCO2e<extra></extra>",
            )
        )
    _apply_layout(fig, title="碳价参考区间", height=360)
    fig.update_layout(
        xaxis=dict(visible=False),
        yaxis_title="元/tCO2e",
        legend=dict(orientation="h", yanchor="top", y=-0.08, xanchor="left", x=0),
        margin=dict(l=55, r=20, t=58, b=90),
    )
    fig.update_yaxes(showgrid=True, gridcolor=GRID)
    return fig


def plot_fleet_comparison(multi_results: List[dict]) -> go.Figure:
    """Compare direct emissions, simulated budgets, and gaps by company."""
    if not multi_results:
        fig = go.Figure()
        _apply_layout(fig, title="企业情景对比", height=300)
        fig.add_annotation(
            text="暂无可比较的企业数据",
            x=0.5,
            y=0.5,
            xref="paper",
            yref="paper",
            showarrow=False,
            font=dict(color=MUTED),
        )
        return fig

    companies = [item.get("company_name", "未命名企业") for item in multi_results]
    emissions = [item.get("total_emission_t", 0) for item in multi_results]
    budgets = [item.get("carbon_budget_t", item.get("total_quota_t", 0)) for item in multi_results]
    gaps = [item.get("budget_gap_t", item.get("gap_t", 0)) for item in multi_results]
    fig = go.Figure()
    for name, values, color in (
        ("直接运营排放", emissions, GREEN),
        ("模拟碳预算", budgets, GRAY),
    ):
        fig.add_trace(
            go.Bar(
                name=name,
                x=companies,
                y=values,
                marker_color=color,
                text=[f"{value:,.0f}" for value in values],
                textposition="outside",
                hovertemplate=f"%{{x}}<br>{name} %{{y:,.2f}} tCO2e<extra></extra>",
            )
        )
    fig.add_trace(
        go.Bar(
            name="预算差额",
            x=companies,
            y=gaps,
            marker_color=[RED if value > 0 else TEAL for value in gaps],
            text=[f"{value:+,.0f}" for value in gaps],
            textposition="outside",
            hovertemplate="%{x}<br>预算差额 %{y:,.2f} tCO2e<extra></extra>",
        )
    )
    _apply_layout(fig, title="企业情景对比", height=420)
    fig.update_layout(
        barmode="group",
        yaxis_title="tCO2e",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=25, r=20, t=85, b=60),
    )
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=True, zerolinecolor=MUTED)
    return fig


def plot_tco_payback_curve(yearly_cashflow: List[float], payback_years: Optional[float] = None) -> go.Figure:
    """绘制新能源替换逐年累计净现金流与静态投资回收期曲线。"""
    if not yearly_cashflow:
        fig = go.Figure()
        _apply_layout(fig, title="投资现金流回收曲线", height=320)
        return fig

    # 转换为万元
    cashflow_wan = [v / 10000.0 for v in yearly_cashflow]
    years_labels = [f"第{i}年 (初始)" if i == 0 else f"第{i}年" for i in range(len(cashflow_wan))]

    fig = go.Figure()

    # 0 轴基准线
    fig.add_trace(
        go.Scatter(
            x=[years_labels[0], years_labels[-1]],
            y=[0, 0],
            mode="lines",
            line=dict(color=MUTED, width=1.5, dash="dash"),
            name="盈亏平衡线",
            hoverinfo="skip",
        )
    )

    # 现金流折线与填充
    fig.add_trace(
        go.Scatter(
            x=years_labels,
            y=cashflow_wan,
            mode="lines+markers+text",
            name="累计净收益",
            line=dict(color=GREEN, width=3),
            marker=dict(size=8, color=[RED if v < 0 else GREEN for v in cashflow_wan]),
            text=[f"{v:+,.1f}万" for v in cashflow_wan],
            textposition="top center",
            hovertemplate="%{x}<br>累计净收益: %{y:+,.2f} 万元<extra></extra>",
        )
    )

    title_text = "新能源替换 · 投资回收现金流曲线"
    if payback_years is not None:
        title_text += f" (预计 {payback_years:.1f} 年回本)"

    _apply_layout(fig, title=title_text, height=340)
    fig.update_layout(
        yaxis_title="累计净收益 (万元)",
        showlegend=False,
        margin=dict(l=40, r=30, t=58, b=40),
    )
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=True, zerolinecolor=MUTED)
    return fig


def plot_tco_cost_breakdown(
    vehicle_type: str,
    replace_count: int,
    annual_km: float,
    single_tco: dict,
    lifespan_years: int = 5,
) -> go.Figure:
    """对比单车或车队在运营周期内燃油车 vs 纯电车的 TCO 成本构成（CAPEX+能耗+维保）。"""
    # 燃油车 5 年成本构成（万元）
    # 单车初始购车
    from src.engine.tco import get_tco_benchmark
    spec = get_tco_benchmark(vehicle_type)
    if not spec:
        fig = go.Figure()
        _apply_layout(fig, title="TCO 成本构成对比", height=320)
        return fig

    count = max(1, replace_count)
    ice_capex = spec.ice_vehicle_price_wan * count
    ev_capex = (spec.ev_vehicle_price_wan + spec.charger_cost_wan) * count

    # 年能耗与维保费用
    fuel_annual = (single_tco.get("annual_fuel_cost_per_vehicle_yuan", 0) * count) / 10000.0
    elec_annual = (single_tco.get("annual_elec_cost_per_vehicle_yuan", 0) * count) / 10000.0
    maint_ice_annual = (spec.annual_maintenance_ice_yuan * count) / 10000.0
    maint_ev_annual = (spec.annual_maintenance_ice_yuan * (1 - spec.maintenance_saving_ratio) * count) / 10000.0

    ice_fuel_total = fuel_annual * lifespan_years
    ev_elec_total = elec_annual * lifespan_years
    ice_maint_total = maint_ice_annual * lifespan_years
    ev_maint_total = maint_ev_annual * lifespan_years

    categories = [f"燃油车 (ICE) · {count}辆", f"纯电车 (EV) · {count}辆"]

    fig = go.Figure()
    # CAPEX
    fig.add_trace(
        go.Bar(
            name="初始购置/建设 CAPEX",
            x=categories,
            y=[ice_capex, ev_capex],
            marker_color="#4f6259",
            text=[f"{ice_capex:,.1f}万", f"{ev_capex:,.1f}万"],
            textposition="inside",
            hovertemplate="%{x}<br>CAPEX: %{y:,.1f} 万元<extra></extra>",
        )
    )
    # OPEX 能耗
    fig.add_trace(
        go.Bar(
            name=f"{lifespan_years}年累计能耗支出",
            x=categories,
            y=[ice_fuel_total, ev_elec_total],
            marker_color=AMBER,
            text=[f"{ice_fuel_total:,.1f}万", f"{ev_elec_total:,.1f}万"],
            textposition="inside",
            hovertemplate="%{x}<br>能耗支出: %{y:,.1f} 万元<extra></extra>",
        )
    )
    # OPEX 维保
    fig.add_trace(
        go.Bar(
            name=f"{lifespan_years}年累计维保支出",
            x=categories,
            y=[ice_maint_total, ev_maint_total],
            marker_color=TEAL,
            text=[f"{ice_maint_total:,.1f}万", f"{ev_maint_total:,.1f}万"],
            textposition="inside",
            hovertemplate="%{x}<br>维保支出: %{y:,.1f} 万元<extra></extra>",
        )
    )

    ice_sum = ice_capex + ice_fuel_total + ice_maint_total
    ev_sum = ev_capex + ev_elec_total + ev_maint_total
    savings = ice_sum - ev_sum

    _apply_layout(
        fig,
        title=f"{lifespan_years}年 TCO 成本构成对比 (纯电比燃油省 {savings:,.1f} 万元)",
        height=360,
    )
    fig.update_layout(
        barmode="stack",
        yaxis_title="总成本 (万元)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        margin=dict(l=35, r=20, t=75, b=40),
    )
    fig.update_yaxes(showgrid=True, gridcolor=GRID)
    return fig


def plot_uncertainty_histogram(hist: dict, point: float, p5: float, p95: float) -> go.Figure:
    """蒙特卡洛抽样分布直方图，标注点估计与 90% 区间。"""
    fig = go.Figure(go.Bar(
        x=hist.get("bin_centers", []), y=hist.get("counts", []),
        marker_color=TEAL, opacity=0.85, name="抽样频数",
        hovertemplate="%{x:,.0f} tCO2e<br>频数 %{y}<extra></extra>",
    ))
    fig.add_vrect(x0=p5, x1=p95, fillcolor=GREEN, opacity=0.08, line_width=0)
    fig.add_vline(x=point, line=dict(color=AMBER, width=2, dash="dash"),
                  annotation_text=f"点估计 {point:,.0f}", annotation_position="top right")
    _apply_layout(fig, title="排放量概率分布（阴影为 90% 区间）", height=360)
    fig.update_xaxes(title="年度直接运营排放 (tCO2e)", gridcolor=GRID)
    fig.update_yaxes(title="频数", gridcolor=GRID)
    fig.update_layout(showlegend=False, bargap=0.05)
    return fig


def plot_uncertainty_contributions(contrib: dict, top: int = 8) -> go.Figure:
    """方差贡献（Spearman ρ² 归一化）横向条形图。"""
    items = list(contrib.items())[:top][::-1]
    fig = go.Figure(go.Bar(
        x=[v * 100 for _, v in items], y=[k for k, _ in items], orientation="h",
        marker_color=[AMBER if k.startswith("排放因子") else GREEN for k, _ in items],
        text=[f"{v:.0%}" for _, v in items], textposition="outside",
        hovertemplate="%{y}: %{x:.1f}%<extra></extra>",
    ))
    _apply_layout(fig, title="不确定性来源贡献（先改进哪项数据）", height=360)
    fig.update_xaxes(title="方差贡献 (%)", gridcolor=GRID, range=[0, max([v * 100 for _, v in items] + [10]) * 1.25])
    fig.update_yaxes(automargin=True)
    return fig


def plot_rag_benchmark(summary: dict, labels: dict) -> go.Figure:
    """RAG 各检索方案 MRR（含 95% CI 误差线）与 Recall@10。"""
    modes = list(summary.keys())
    names = [labels.get(m, m) for m in modes]
    mrr = [summary[m]["MRR"] for m in modes]
    err_hi = [summary[m].get("MRR_CI95", [v, v])[1] - v for m, v in zip(modes, mrr)]
    err_lo = [v - summary[m].get("MRR_CI95", [v, v])[0] for m, v in zip(modes, mrr)]
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=names, y=mrr, name="MRR", marker_color=GREEN,
        error_y=dict(type="data", array=err_hi, arrayminus=err_lo, color=INK, thickness=1.2),
        text=[f"{v:.3f}" for v in mrr], textposition="inside", insidetextanchor="start",
    ))
    fig.add_trace(go.Scatter(
        x=names, y=[summary[m]["Recall@10"] for m in modes], name="Recall@10",
        mode="lines+markers", line=dict(color=AMBER, width=2), marker=dict(size=9),
    ))
    _apply_layout(fig, title="检索方案对照（40 题金标集，误差线为 95% Bootstrap CI）", height=420)
    fig.update_yaxes(range=[0, 1], gridcolor=GRID, tickformat=".0%")
    fig.update_layout(legend=dict(orientation="h", y=-0.18))
    return fig
