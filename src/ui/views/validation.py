"""方法与验证页：把模型口径、实证误差与 RAG 评测证据集中展示（答辩用）。"""

from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from src.ui.components.charts import plot_rag_benchmark
from src.ui.theme import notice, page_header

ROOT = Path(__file__).resolve().parents[3]
RAG_RESULTS = ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json"
DERIVED = ROOT / "docs" / "derived_metrics.json"


def _load(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def render_validation() -> None:
    page_header(
        "方法与验证",
        "模型可信度证据",
        "核算口径、真实车队对标误差、不确定性方法与政策检索评测，全部可由仓库脚本复现。",
    )

    st.markdown("## 一、核算模型")
    st.latex(r"E=\sum_i \frac{n_i\,d_i\,EF_i\,LF_i}{1000},\qquad "
             r"LF_i=\begin{cases}1+\alpha(0.75-l_i), & l_i<0.75\\ 1, & l_i\ge 0.75\end{cases}")
    st.caption("E：年度直接运营排放 (tCO2e)；n：车辆数；d：年均里程；EF：车公里排放因子；"
               "LF：低满载率保守偏置系数（α=0.15，上限 1.1125）。核算边界为 Scope 1 Tank-to-Wheel。")

    derived = _load(DERIVED)
    if derived and derived.get("mape"):
        m = derived["mape"]
        st.markdown("## 二、真实车队对标（RQ1）")
        sens = derived.get("sensitivity", {})
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("标定点误差 · 4 家车队", f"{m['equal_weight_pct']:.2f}%",
                  help="等权 MAPE。样本为数据完整的大型车队，是“标定点”，不代表任意企业的精度。")
        c2.metric("标定点区间", f"{m['min_pct']:.1f}% – {m['max_pct']:.1f}%")
        if sens:
            c3.metric("误差包络 · 中位", f"{sens['median_pct']:.2f}%",
                      help=f"{sens['n']} 种里程/满载率偏差组合下的 MAPE 中位数，"
                           f"范围 {sens['min_pct']:.1f}%–{sens['max_pct']:.1f}%。")
        c4.metric("去掉 LF 偏置后", f"{m['equal_weight_no_lf_pct']:.2f}%",
                  delta=f"{m['equal_weight_no_lf_pct'] - m['equal_weight_pct']:+.2f} pp",
                  delta_color="inverse")
        rows = [
            {"样本": c["company"], "车辆数": f"{c['vehicles_total']:,}",
             "模型估算 (t)": f"{c['e_model_tco2']:,.0f}", "燃料台账 (t)": f"{c['e_fuel_tco2']:,.0f}",
             "相对误差": f"{c['rel_err_pct']:+.2f}%",
             "无 LF 误差": (f"{c['rel_err_no_lf_pct']:+.2f}%" if "rel_err_no_lf_pct" in c else "—")}
            for c in derived.get("fleet_cases", [])
        ]
        st.dataframe(rows, hide_index=True, width="stretch")
        notice(
            "精度口径（三句式）",
            f"① 标定点：在 {m['n_cases']} 家数据完整的大型车队（{m['vehicles_total']:,} 辆）上，"
            f"模型与燃料台账的等权误差为 {m['equal_weight_pct']:.2f}%；"
            + (f"② 误差包络：当里程、满载率等输入存在常见偏差时，误差中位约 {sens['median_pct']:.1f}%，"
               f"最坏 {sens['max_pct']:.1f}%；" if sens else "② 误差包络：见敏感性分析；")
            + "③ 适用边界：适用于有车型与年里程台账的车队做 Scope 1 直接排放估算，"
            "不替代逐车油耗计量，也不构成碳市场履约核查。"
            f" LF 偏置为保守设计，去掉后标定点误差降至 {m['equal_weight_no_lf_pct']:.2f}%，"
            "即以约 0.7 个百分点的精度换取对低满载车队不低估。",
        )
        st.caption("数据与方法见 data/raw/real_fleets/ 与 docs/real_fleet_validation_report.md；"
                   "复现：python scripts/verify_real_fleets.py")

    st.markdown("## 三、不确定性分析（IPCC 2006 Approach 2）")
    st.markdown(
        "- **排放因子**：同一车型的多来源取值（《中国环境科学》2021、GB 30510-2024/2018、实测）构成三角分布，"
        "相对半宽不低于 10%\n"
        "- **年均里程**：正态分布，变异系数按数据质量取 5% / 10% / 20%\n"
        "- **满载率**：均匀分布 ±0.05\n"
        "- **输出**：P5 / P50 / P95、相对不确定度，以及 Spearman ρ² 归一化的方差贡献排序\n\n"
        "在「排放盘点」页完成核算后即可运行。"
    )

    rag = _load(RAG_RESULTS)
    st.markdown("## 四、政策检索评测（RQ2）")
    if not rag:
        st.info("尚未生成评测结果，运行 python scripts/evaluate_rag_benchmark.py 后刷新本页。")
    else:
        meta = rag.get("benchmark_metadata", {})
        summary = rag["summary_metrics"]
        labels = rag.get("mode_labels", {m: m for m in summary})
        st.caption(
            f"金标集 {meta.get('total_questions')} 题 · 知识库 {meta.get('total_documents', '—')} 份文件 / "
            f"{meta.get('total_chunks')} 块 · 嵌入模型 {meta.get('embedding_model')}"
        )
        st.plotly_chart(plot_rag_benchmark(summary, labels), width="stretch",
                        config={"displayModeBar": False})
        table = []
        for mode, s in summary.items():
            ci = s.get("MRR_CI95")
            table.append({
                "方案": labels.get(mode, mode),
                "MRR": f"{s['MRR']:.3f}" + (f" [{ci[0]:.2f}, {ci[1]:.2f}]" if ci else ""),
                "Recall@3": f"{s['Recall@3']:.0%}",
                "Recall@10": f"{s['Recall@10']:.0%}",
                "nDCG@10": f"{s['nDCG@10']:.3f}" if "nDCG@10" in s else "—",
            })
        st.dataframe(table, hide_index=True, width="stretch")
        sig = rag.get("statistical_significance", {})
        if sig:
            with st.expander("配对 Wilcoxon 检验（Holm 校正）"):
                st.dataframe(
                    [{"比较": k, "原始 p": v["p_value"], "Holm p": v.get("p_holm", "—"),
                      "显著(α=0.05)": "是" if v["is_significant_005"] else "否"} for k, v in sig.items()],
                    hide_index=True, width="stretch",
                )
        abl = rag.get("embedding_ablation")
        if abl:
            with st.expander("嵌入模型消融"):
                st.dataframe(
                    [{"嵌入模型": k, "纯向量 MRR": f"{v['vector']['MRR']:.3f}",
                      "纯向量 Recall@10": f"{v['vector']['Recall@10']:.0%}"} for k, v in abl.items()],
                    hide_index=True, width="stretch",
                )

    _render_carbon_price_quality(derived)

    notice(
        "研究边界",
        "物流运输行业目前未纳入全国碳市场配额管理；新能源车仅按直接排放为零核算。"
        "评测集规模有限（40 题），结论以置信区间解读，后续扩充后复测。",
        amber=True,
    )


def _render_carbon_price_quality(derived: dict | None) -> None:
    """碳价数据质量：真实成交点与插值点分色展示，避免把插值当历史数据。"""
    from src.engine.carbon_price import load_carbon_price_data, price_window_stats
    from src.ui.components.charts import plot_carbon_price_history

    df = load_carbon_price_data()
    if df is None or df.empty:
        return
    st.markdown("## 五、碳价数据质量")
    w = price_window_stats(df)
    n_real = int((df["数据来源"] == "真实数据").sum())
    c1, c2, c3 = st.columns(3)
    c1.metric("最新收盘价", f"{w['current']:.2f} 元/t", help=f"截至 {df['日期'].max().date()}")
    c2.metric("近 90 日均价 · 真实成交", f"{w['mean']:.2f} 元/t",
              help=f"{w['window_start']} 至 {w['window_end']}，共 {w['n_obs']} 个真实成交点")
    c3.metric("真实数据占比", f"{n_real / len(df):.0%}", help=f"{n_real} / {len(df)} 行，其余为周频线性插值")
    st.plotly_chart(plot_carbon_price_history(df), width="stretch", config={"displayModeBar": False})
    st.caption("情景成本只使用近 90 个自然日内的真实成交点计算；插值点仅用于绘制趋势，不参与任何统计。")
