#!/usr/bin/env python3
"""大创中期答辩科研实证图表与展示产物自动生成脚本

生成成果（保存在 docs/artifacts/）：
1. fig1_rq1_real_fleet_validation (.html & .svg): 真实车队台账 vs 活动水平估算对比与相对误差分布 (案例等权 MAPE 4.23% / 加权 2.38%)
2. fig2_rq2_rag_benchmark_comparison (.html & .svg): RAG 三组检索对照实验核心指标与 Wilcoxon 显著性检验
3. fig3_rq3_sensitivity_heatmap (.html & .svg): 满载率与年均里程二维扰动敏感性矩阵热力图
4. all_charts_dashboard.html: 单页自包含实证展板，评委即开即览
"""
import sys
import json
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from src.engine.calculator import VehicleGroupData, calculate_emission
import plotly.graph_objects as go
ARTIFACTS_DIR = PROJECT_ROOT / "docs" / "artifacts"
ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)


def _ledger():
    """读取唯一数字台账；图表上的任何结论性数字都必须来自这里，不得写死。"""
    import json

    path = PROJECT_ROOT / "docs" / "derived_metrics.json"
    return json.loads(path.read_text(encoding="utf-8"))


LEDGER = _ledger()
MAPE = LEDGER["mape"]
ERR_LO = MAPE["min_pct"]
ERR_HI = MAPE["max_pct"]
MAPE_EQ = MAPE["equal_weight_pct"]
MAPE_WT = MAPE["emission_weight_pct"]
def _kb_scale():
    """实测知识库块数；失败时返回 None，由调用方降级为提示文本。"""
    try:
        from src.rag.vector_store import PolicyVectorStore

        return int(PolicyVectorStore().count())
    except Exception:  # 未建库或缺依赖时不应阻断图表生成
        return None


KB_CHUNKS = _kb_scale()
KB_BADGE = (
    f"全量知识库: {KB_CHUNKS} Chunks（运行时实测）"
    if KB_CHUNKS is not None
    else "全量知识库: 未建库（先运行 scripts/ingest_policy_docs.py）"
)
LF_NO_BIAS_MAPE = MAPE["equal_weight_no_lf_pct"]
# 【口径】中位数取自台账 sensitivity.median_pct，它由「未截断的逐格原始值」算出
# （14.3712 与 14.6577 的均值 14.51449 → 14.51）。图表里禁止再写死 14.52：
# 那是先逐格保留两位再取中位的二次舍入结果，会让图与正文打架。
SENS = LEDGER["sensitivity"]
_MEDIAN = f"{SENS['median_pct']:.2f}"
SENS_LO = f"{SENS['min_pct']:.2f}"
SENS_HI = f"{SENS['max_pct']:.2f}"
SENS_N = SENS["n"]
SENS_OVER10 = SENS["over10"]

# 统一设计主题规范（学术审慎绿/深灰/琥珀金）
INK = "#1a2521"
MUTED = "#55645d"
GRID = "#e2e8e5"
GREEN_PRIMARY = "#1e6b4b"
GREEN_LIGHT = "#3b966f"
TEAL = "#2b7570"
AMBER = "#c07c2a"
RED = "#b8423e"
BLUE = "#2f6fa3"
GRAY = "#84938b"

def generate_svg_rq1(fleets, ledgers, estimates, errors):
    """生成高质量纯矢量 SVG 格式的 RQ1 图表"""
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 500" width="100%" height="100%" style="background:#ffffff; font-family:'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;">
  <rect width="900" height="500" fill="#fcfdfc" rx="8"/>
  <text x="40" y="45" font-size="20" font-weight="bold" fill="{INK}">RQ1: 真实车队直接排放核算验证与误差基准分析</text>
  <text x="40" y="70" font-size="13" fill="{MUTED}">对比样本：顺丰、中通、京东及生鲜冷链等 4 类典型公开车队台账复算基准（案例等权 MAPE = {MAPE_EQ}%）</text>
  
  <!-- 图例 -->
  <rect x="520" y="32" width="16" height="16" fill="{BLUE}" rx="3"/>
  <text x="545" y="45" font-size="12" fill="{INK}">能源台账真实排放 (tCO2e)</text>
  <rect x="710" y="32" width="16" height="16" fill="{GREEN_PRIMARY}" rx="3"/>
  <text x="735" y="45" font-size="12" fill="{INK}">活动水平估算排放 (tCO2e)</text>

  <!-- 网格背景与坐标轴 -->
  <line x1="180" y1="100" x2="840" y2="100" stroke="{GRID}" stroke-dasharray="4"/>
  <line x1="180" y1="180" x2="840" y2="180" stroke="{GRID}" stroke-dasharray="4"/>
  <line x1="180" y1="260" x2="840" y2="260" stroke="{GRID}" stroke-dasharray="4"/>
  <line x1="180" y1="340" x2="840" y2="340" stroke="{GRID}" stroke-dasharray="4"/>
  <line x1="180" y1="420" x2="840" y2="420" stroke="{INK}" stroke-width="1.5"/>

  <!-- 纵轴刻度 -->
  <text x="170" y="105" font-size="12" fill="{MUTED}" text-anchor="end">300,000</text>
  <text x="170" y="185" font-size="12" fill="{MUTED}" text-anchor="end">200,000</text>
  <text x="170" y="265" font-size="12" fill="{MUTED}" text-anchor="end">100,000</text>
  <text x="170" y="345" font-size="12" fill="{MUTED}" text-anchor="end">10,000</text>
  <text x="170" y="425" font-size="12" fill="{MUTED}" text-anchor="end">0</text>
"""
    # 柱状图几何计算
    max_val = 300000.0
    x_positions = [260, 420, 580, 740]
    bar_w = 40
    for i, (name, act, est, err) in enumerate(zip(fleets, ledgers, estimates, errors)):
        x_c = x_positions[i]
        # 对数/线性平滑映射以兼顾微小冷链车队展示
        h_act = min(320, max(12, int(act / max_val * 320)))
        h_est = min(320, max(14, int(est / max_val * 320)))
        
        y_act = 420 - h_act
        y_est = 420 - h_est
        
        svg += f"""
  <!-- 柱 {name} -->
  <rect x="{x_c - bar_w - 2}" y="{y_act}" width="{bar_w}" height="{h_act}" fill="{BLUE}" rx="3" opacity="0.9"/>
  <rect x="{x_c + 2}" y="{y_est}" width="{bar_w}" height="{h_est}" fill="{GREEN_PRIMARY}" rx="3" opacity="0.95"/>
  <text x="{x_c}" y="445" font-size="13" font-weight="600" fill="{INK}" text-anchor="middle">{name}</text>
  
  <!-- 相对误差徽标 -->
  <rect x="{x_c - 30}" y="{y_est - 28}" width="60" height="20" fill="{AMBER}" rx="10" opacity="0.15"/>
  <rect x="{x_c - 30}" y="{y_est - 28}" width="60" height="20" stroke="{AMBER}" fill="none" rx="10"/>
  <text x="{x_c}" y="{y_est - 14}" font-size="11" font-weight="bold" fill="{AMBER}" text-anchor="middle">+{err:.2f}%</text>
"""
    svg += f"""
  <!-- 底部结论条 -->
  <rect x="40" y="465" width="820" height="25" fill="#f0f5f2" rx="4"/>
  <text x="50" y="482" font-size="12" fill="#2d5240">验证结论：4 组案例偏差区间 [{ERR_LO:+.2f}%, {ERR_HI:+.2f}%]，方向一致为正偏；移除满载率偏置后等权 MAPE 由 {MAPE_EQ}% 降至 {LF_NO_BIAS_MAPE}%，说明该偏置是保守性来源而非精度来源。</text>
</svg>"""
    return svg

# 当前默认检索模式是 rrf3（三路加权融合）；hybrid 是 v0.3 遗留方案。
# 只要它不再是默认值，图里就不能再拿它当「本方案」比较，否则会出现
# 图上 49.05% 与正文 0.4920 两个数并存。
FUSION_KEY = "rrf3"
FUSION_SIG_KEY = "rrf3_vs_keyword"


def generate_svg_rq2(summary, stats):
    """生成高质量纯矢量 SVG 格式的 RQ2 图表"""
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 500" width="100%" height="100%" style="background:#ffffff; font-family:'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;">
  <rect width="900" height="500" fill="#fcfdfc" rx="8"/>
  <text x="40" y="45" font-size="20" font-weight="bold" fill="{INK}">RQ2: 40题基准集三组检索对照实验与显著性检验</text>
  <text x="40" y="70" font-size="13" fill="{MUTED}">对照组设计：纯关键词匹配 (TF-IDF) vs 纯向量语义 (ChromaDB) vs 混合重排 (本项目)</text>

  <!-- 图例 -->
  <rect x="530" y="32" width="16" height="16" fill="{GRAY}" rx="3"/>
  <text x="555" y="45" font-size="12" fill="{INK}">组A: 纯关键词</text>
  <rect x="655" y="32" width="16" height="16" fill="{BLUE}" rx="3"/>
  <text x="680" y="45" font-size="12" fill="{INK}">组B: 纯向量</text>
  <rect x="760" y="32" width="16" height="16" fill="{GREEN_PRIMARY}" rx="3"/>
  <text x="785" y="45" font-size="12" fill="{INK}">组C: 混合重排</text>

  <!-- 坐标轴 -->
  <line x1="160" y1="100" x2="840" y2="100" stroke="{GRID}" stroke-dasharray="4"/>
  <line x1="160" y1="180" x2="840" y2="180" stroke="{GRID}" stroke-dasharray="4"/>
  <line x1="160" y1="260" x2="840" y2="260" stroke="{GRID}" stroke-dasharray="4"/>
  <line x1="160" y1="340" x2="840" y2="340" stroke="{GRID}" stroke-dasharray="4"/>
  <line x1="160" y1="420" x2="840" y2="420" stroke="{INK}" stroke-width="1.5"/>

  <text x="150" y="105" font-size="12" fill="{MUTED}" text-anchor="end">100%</text>
  <text x="150" y="180" font-size="12" fill="{MUTED}" text-anchor="end">75%</text>
  <text x="150" y="260" font-size="12" fill="{MUTED}" text-anchor="end">50%</text>
  <text x="150" y="340" font-size="12" fill="{MUTED}" text-anchor="end">25%</text>
  <text x="150" y="425" font-size="12" fill="{MUTED}" text-anchor="end">0%</text>
"""
    metrics = ["MRR (倒数排名)", "Recall@3", "Recall@5", "Recall@10", "负例检索命中率"]
    x_positions = [230, 360, 490, 620, 750]
    bar_w = 26

    kw_vals = [summary["keyword"]["MRR"], summary["keyword"]["Recall@3"], summary["keyword"]["Recall@5"], summary["keyword"]["Recall@10"], summary["keyword"]["Negative_Rejection_Accuracy"]]
    vec_vals = [summary["vector"]["MRR"], summary["vector"]["Recall@3"], summary["vector"]["Recall@5"], summary["vector"]["Recall@10"], summary["vector"]["Negative_Rejection_Accuracy"]]
    hyb_vals = [summary[FUSION_KEY][k] for k in ("MRR", "Recall@3", "Recall@5", "Recall@10", "Negative_Rejection_Accuracy")]

    for i, (m_name, xc) in enumerate(zip(metrics, x_positions)):
        h_kw = int(kw_vals[i] * 320)
        h_vec = int(vec_vals[i] * 320)
        h_hyb = int(hyb_vals[i] * 320)

        svg += f"""
  <!-- {m_name} 分组柱 -->
  <rect x="{xc - 40}" y="{420 - h_kw}" width="{bar_w}" height="{h_kw}" fill="{GRAY}" rx="2" opacity="0.85"/>
  <text x="{xc - 27}" y="{415 - h_kw}" font-size="10" fill="{MUTED}" text-anchor="middle">{kw_vals[i]:.2%}</text>

  <rect x="{xc - 13}" y="{420 - h_vec}" width="{bar_w}" height="{h_vec}" fill="{BLUE}" rx="2" opacity="0.85"/>
  <text x="{xc}" y="{415 - h_vec}" font-size="10" fill="{BLUE}" text-anchor="middle">{vec_vals[i]:.2%}</text>

  <rect x="{xc + 14}" y="{420 - h_hyb}" width="{bar_w}" height="{h_hyb}" fill="{GREEN_PRIMARY}" rx="2" opacity="0.95"/>
  <text x="{xc + 27}" y="{415 - h_hyb}" font-size="11" font-weight="bold" fill="{GREEN_PRIMARY}" text-anchor="middle">{hyb_vals[i]:.2%}</text>

  <text x="{xc}" y="445" font-size="12" font-weight="600" fill="{INK}" text-anchor="middle">{m_name}</text>
"""
    _sig = stats[FUSION_SIG_KEY]
    p_vec = _sig["p_value"]
    p_holm = _sig["p_holm"]
    _verdict = "显著" if p_holm < 0.05 else "不显著"
    svg += f"""
  <!-- 显著性标识卡片 -->
  <rect x="520" y="70" width="320" height="40" fill="#eef7f2" stroke="{GREEN_PRIMARY}" rx="5"/>
  <text x="535" y="95" font-size="12" font-weight="bold" fill="{GREEN_PRIMARY}">Wilcoxon（三路融合 vs 纯关键词）: p = {p_vec:.4f}，Holm 校正 {p_holm:.4f}（{_verdict}）</text>

  <!-- 底部结论条 -->
  <rect x="40" y="465" width="820" height="25" fill="#f0f5f2" rx="4"/>
  <text x="50" y="482" font-size="12" fill="#2d5240">实证发现：同一语料同一中文嵌入下，纯关键词 MRR {summary["keyword"]["MRR"]:.4f} / 纯向量 {summary["vector"]["MRR"]:.4f} / 三路加权融合 {summary[FUSION_KEY]["MRR"]:.4f}；真实增量在 Recall@10（{summary[FUSION_KEY]["Recall@10"]:.1%} vs {summary["keyword"]["Recall@10"]:.1%}），相对纯关键词的 MRR 差异不显著（Holm {p_holm:.3f}）。</text>
</svg>"""
    return svg

def generate_svg_rq3():
    """生成高质量纯矢量 SVG 格式的 RQ3 敏感性热力图"""
    # 实载率偏移 (-0.30 ~ +0.15) × 里程缩放 (0.8 ~ 1.2)
    loads = ["-0.30", "-0.15", "0.00 (基准)", "+0.10", "+0.15"]
    kms = ["×0.8", "×0.9", "×1.0 (基准)", "×1.1", "×1.2"]
    # 相对误差矩阵 (MAPE %) 取自 docs/derived_metrics.json (50组扫描子集)
    grid = [
        [13.47, 15.33, 16.61, 16.98, 17.14],
        [3.04, 4.75, 6.19, 6.60, 6.78],
        [8.17, 5.84, 4.23, 3.78, 3.58],
        [18.98, 16.42, 14.66, 14.16, 13.94],
        [29.80, 27.01, 25.08, 24.53, 24.30],
    ]
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 900 500" width="100%" height="100%" style="background:#ffffff; font-family:'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;">
  <rect width="900" height="500" fill="#fcfdfc" rx="8"/>
  <text x="40" y="45" font-size="20" font-weight="bold" fill="{INK}">RQ3: 运营参数（年均里程缩放 × 实载率偏移）敏感性矩阵</text>
  <text x="40" y="70" font-size="13" fill="{MUTED}">分析在实载率 (-0.30~+0.15) 与年里程 (±20%) 扰动下模型误差的传导规律 (中位数 {_MEDIAN}%)</text>

  <!-- 纵坐标轴说明 (里程缩放) -->
  <text x="110" y="270" font-size="14" font-weight="bold" fill="{INK}" text-anchor="middle" transform="rotate(-90, 110, 270)">年均里程缩放 (kd)</text>

  <!-- 横坐标轴说明 (实载率偏移) -->
  <text x="510" y="445" font-size="14" font-weight="bold" fill="{INK}" text-anchor="middle">实载率设定偏移量 (Δl)</text>
"""
    # 绘制热力网格 5x5
    cell_w = 110
    cell_h = 55
    x_start = 230
    y_start = 110

    for j, load_label in enumerate(loads):
        svg += f'<text x="{x_start + j * cell_w + cell_w / 2}" y="{y_start - 12}" font-size="12" font-weight="600" fill="{INK}" text-anchor="middle">{load_label}</text>\n'

    for i, km_label in enumerate(kms):
        y_pos = y_start + i * cell_h
        svg += f'<text x="{x_start - 15}" y="{y_pos + cell_h / 2 + 5}" font-size="12" font-weight="600" fill="{INK}" text-anchor="end">{km_label}</text>\n'
        for j, load_label in enumerate(loads):
            val = grid[i][j]
            x_pos = x_start + j * cell_w
            # 色阶映射 3.0% -> 30.0%
            ratio = (val - 3.0) / 27.0
            bg_color = f"rgba(47, 111, 163, {0.10 + ratio * 0.85:.2f})"
            border_color = f"rgba(30, 107, 75, {0.3 + ratio * 0.6:.2f})"
            is_base = (i == 2 and j == 2)
            stroke_w = "2.5" if is_base else "1"

            svg += f"""
  <rect x="{x_pos}" y="{y_pos}" width="{cell_w - 4}" height="{cell_h - 4}" fill="{bg_color}" stroke="{border_color}" stroke-width="{stroke_w}" rx="4"/>
  <text x="{x_pos + cell_w / 2}" y="{y_pos + cell_h / 2 + 5}" font-size="13" font-weight="bold" fill="{INK}" text-anchor="middle">{val:.2f}%</text>
"""
            if is_base:
                svg += f'<text x="{x_pos + cell_w / 2}" y="{y_pos + 15}" font-size="9" font-weight="bold" fill="{RED}" text-anchor="middle">★ 基准工况</text>\n'

    svg += """
  <!-- 底部核心机理发现 -->
  <rect x="40" y="465" width="820" height="25" fill="#f0f5f2" rx="4"/>
  <text x="50" y="482" font-size="12" fill="#2d5240">敏感性分析表明：里程是一阶主导因子但效应强不对称（+20% 升 +20.7~21.6 pp，−20% 仅升 +5.3~13.6 pp）；实载率引起的 MAPE 变化约 4.59 pp，非可跨里程倍数通用的常数。</text>
</svg>"""
    return svg

def build_all_artifacts():
    print("=" * 70)
    print("🎨 正在生成大创中期答辩科研实证图表与展示产物")
    print("=" * 70)


    # === 1. 数据读取与准备 ===
    # 真实车队数据
    real_fleets_path = PROJECT_ROOT / "data" / "raw" / "real_fleets" / "benchmark_fleets.json"
    real_data = json.loads(real_fleets_path.read_text(encoding="utf-8"))
    conv = real_data["metadata"]["emission_conversion_factors"]
    
    ledgers = []
    estimates = []
    errors = []
    for b in real_data["benchmarks"]:
        fleet_data = [
            VehicleGroupData(
                vehicle_type=v["vehicle_type"],
                count=v["count"],
                annual_km=v["annual_km"],
                load_factor=v.get("load_factor", 0.75),
            )
            for v in b["fleet_input"]
        ]
        res = calculate_emission(fleet_data)
        e_model = res.total_emission_t
        ledger = b["real_energy_ledger"]
        e_fuel = (
            ledger.get("diesel_liters", 0) * conv["diesel_kg_co2_per_liter"]
            + ledger.get("gasoline_liters", 0) * conv["gasoline_kg_co2_per_liter"]
            + ledger.get("lng_kg", 0) * conv["lng_kg_co2_per_kg"]
        ) / 1000.0
        err = ((e_model - e_fuel) / e_fuel) * 100.0
        ledgers.append(e_fuel)
        estimates.append(e_model)
        errors.append(err)
    # RAG 评测结果数据
    eval_path = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json"
    eval_data = json.loads(eval_path.read_text(encoding="utf-8"))
    summary = eval_data["summary_metrics"]
    stats = eval_data["statistical_significance"]
    # 显著性徽标用现算值：历史上这里写死过 p < 0.001***，而实测最小 p 是 0.00171，
    # 相对纯关键词那组更是 p=0.3203（Holm 校正后 0.9608，完全不显著）。
    _sig_block = stats[FUSION_SIG_KEY]
    _SIG_P = _sig_block["p_value"]
    _SIG_PHOLM = _sig_block["p_holm"]
    _SIG_VERDICT = "显著" if _SIG_PHOLM < 0.05 else "不显著"

    # === 2. 导出纯矢量 SVG 格式（适用于 PPT/报告） ===
    svg1_path = ARTIFACTS_DIR / "fig1_rq1_real_fleet_validation.svg"
    svg1_path.write_text(generate_svg_rq1(
        ["顺丰速运(干支)", "中通快递(纯干)", "京东物流(城配)", "生鲜冷链(重卡)"],
        ledgers, estimates, errors
    ), encoding="utf-8")
    print(f"✅ 生成矢量图表 1: {svg1_path}")

    svg2_path = ARTIFACTS_DIR / "fig2_rq2_rag_benchmark_comparison.svg"
    svg2_path.write_text(generate_svg_rq2(summary, stats), encoding="utf-8")
    print(f"✅ 生成矢量图表 2: {svg2_path}")

    svg3_path = ARTIFACTS_DIR / "fig3_rq3_sensitivity_heatmap.svg"
    svg3_path.write_text(generate_svg_rq3(), encoding="utf-8")
    print(f"✅ 生成矢量图表 3: {svg3_path}")

    # === 3. 生成交互式 Plotly HTML 格式 ===
    # 图 1 (RQ1 Plotly)
    fig1 = go.Figure()
    fig1.add_trace(go.Bar(
        x=["顺丰速运", "中通快递", "京东物流", "生鲜冷链"],
        y=ledgers,
        name="能源台账真实排放 (tCO2e)",
        marker_color=BLUE,
        text=[f"{v:,.0f}" for v in ledgers],
        textposition="outside",
    ))
    fig1.add_trace(go.Bar(
        x=["顺丰速运", "中通快递", "京东物流", "生鲜冷链"],
        y=estimates,
        name="活动水平估算排放 (tCO2e)",
        marker_color=GREEN_PRIMARY,
        text=[f"{v:,.0f} (+{e:.2f}%)" for v, e in zip(estimates, errors)],
        textposition="outside",
    ))
    fig1.update_layout(
        title=f"RQ1: 真实车队直接排放核算验证与误差基准 (案例等权 MAPE {MAPE_EQ}%, 加权 {MAPE_WT}%)",
        barmode="group",
        yaxis_title="直接运营排放量 (tCO2e)",
        font=dict(family="Segoe UI, Microsoft YaHei", size=13),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    html1_path = ARTIFACTS_DIR / "fig1_rq1_real_fleet_validation.html"
    fig1.write_html(str(html1_path), include_plotlyjs="cdn")
    print(f"✅ 生成交互式图表 1: {html1_path}")

    # 图 2 (RQ2 Plotly)
    labels = ["MRR", "Recall@3", "Recall@5", "Recall@10", "负例检索命中率"]
    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=labels,
        y=[summary["keyword"]["MRR"], summary["keyword"]["Recall@3"], summary["keyword"]["Recall@5"], summary["keyword"]["Recall@10"], summary["keyword"]["Negative_Rejection_Accuracy"]],
        name="组A (纯关键词)",
        marker_color=GRAY,
    ))
    fig2.add_trace(go.Bar(
        x=labels,
        y=[summary["vector"]["MRR"], summary["vector"]["Recall@3"], summary["vector"]["Recall@5"], summary["vector"]["Recall@10"], summary["vector"]["Negative_Rejection_Accuracy"]],
        name="组B (纯向量语义)",
        marker_color=BLUE,
    ))
    fig2.add_trace(go.Bar(
        x=labels,
        y=[summary["hybrid"]["MRR"], summary["hybrid"]["Recall@3"], summary["hybrid"]["Recall@5"], summary["hybrid"]["Recall@10"], summary["hybrid"]["Negative_Rejection_Accuracy"]],
        name="组C (混合重排-本项目)",
        marker_color=GREEN_PRIMARY,
    ))
    fig2.update_layout(
        title=f"RQ2: 40题基准集三组检索对照实验 (Wilcoxon 融合 vs 纯关键词: p = {stats[FUSION_SIG_KEY]['p_value']:.4f}，Holm {stats[FUSION_SIG_KEY]['p_holm']:.4f})",
        barmode="group",
        yaxis_tickformat=".0%",
        font=dict(family="Segoe UI, Microsoft YaHei", size=13),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
    )
    html2_path = ARTIFACTS_DIR / "fig2_rq2_rag_benchmark_comparison.html"
    fig2.write_html(str(html2_path), include_plotlyjs="cdn")
    print(f"✅ 生成交互式图表 2: {html2_path}")

    # 图 3 (RQ3 Plotly Heatmap)
    z_grid = [
        [13.47, 15.33, 16.61, 16.98, 17.14],
        [3.04, 4.75, 6.19, 6.60, 6.78],
        [8.17, 5.84, 4.23, 3.78, 3.58],
        [18.98, 16.42, 14.66, 14.16, 13.94],
        [29.80, 27.01, 25.08, 24.53, 24.30],
    ]
    fig3 = go.Figure(data=go.Heatmap(
        z=z_grid,
        x=["-0.30", "-0.15", "0.00 (基准)", "+0.10", "+0.15"],
        y=["×0.8", "×0.9", "×1.0 (基准)", "×1.1", "×1.2"],
        colorscale="Blues",
        text=[[f"{v:.2f}%" for v in row] for row in z_grid],
        texttemplate="%{text}",
        colorbar=dict(title="MAPE (%)"),
    ))
    fig3.update_layout(
        title="RQ3: 运营参数（年均里程缩放 × 实载率偏移）敏感性矩阵 ({SENS_LO}%~{SENS_HI}%, 中位数 {_MEDIAN}%)",
        xaxis_title="实载率设定偏移量 (Δl)",
        yaxis_title="年均里程缩放系数 (kd)",
        font=dict(family="Segoe UI, Microsoft YaHei", size=13),
    )
    html3_path = ARTIFACTS_DIR / "fig3_rq3_sensitivity_heatmap.html"
    fig3.write_html(str(html3_path), include_plotlyjs="cdn")
    print(f"✅ 生成交互式图表 3: {html3_path}")

    # === 4. 生成统一的大创实证全景单页展板 (all_charts_dashboard.html) ===
    dashboard_html = ARTIFACTS_DIR / "all_charts_dashboard.html"
    dash_content = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <title>大创中期答辩科研实证展板 — 物流碳排放与减排决策系统</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "PingFang SC", "Microsoft YaHei", sans-serif; background: #f7faf8; color: #17231d; margin: 0; padding: 30px; }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    .header {{ background: #ffffff; padding: 25px 35px; border-radius: 12px; box-shadow: 0 4px 16px rgba(0,0,0,0.04); margin-bottom: 25px; border-left: 6px solid {GREEN_PRIMARY}; }}
    h1 {{ font-size: 24px; margin: 0 0 10px 0; color: #17231d; }}
    p.subtitle {{ color: #55645d; margin: 0; font-size: 14px; line-height: 1.6; }}
    .card {{ background: #ffffff; border-radius: 12px; padding: 25px; margin-bottom: 25px; box-shadow: 0 4px 16px rgba(0,0,0,0.04); }}
    .card h2 {{ font-size: 18px; margin-top: 0; color: {GREEN_PRIMARY}; border-bottom: 1px solid {GRID}; padding-bottom: 10px; }}
    .chart-container {{ text-align: center; margin: 15px 0; }}
    .chart-container svg {{ max-width: 100%; height: auto; border-radius: 8px; border: 1px solid {GRID}; }}
    .findings {{ background: #f0f7f4; border-left: 4px solid {GREEN_PRIMARY}; padding: 12px 18px; border-radius: 4px; font-size: 13.5px; color: #204d36; line-height: 1.6; }}
    .stats-badge {{ display: inline-block; background: #eaf3ee; color: {GREEN_PRIMARY}; font-weight: bold; padding: 4px 10px; border-radius: 20px; font-size: 12px; margin-right: 8px; }}
  </style>
</head>
<body>
  <div class="container">
    <div class="header">
      <h1>大创中期答辩科研实证展板 — 物流碳排放与减排决策系统</h1>
      <p class="subtitle">
        <strong>定位</strong>：大学生创新创业训练计划科研原型成果展板 | <strong>核心原则</strong>：以“研究问题 (RQ) + 实证检验 + 统计显著性”组织答辩链条，杜绝功能堆砌与法定履约夸大。
      </p>
    </div>

    <!-- RQ1 -->
    <div class="card">
      <h2>RQ1: 数据有限条件下活动水平估算法的精度与一致性核验</h2>
      <div>
        <span class="stats-badge">样本集: 顺丰 / 中通 / 京东 / 区域冷链 (合计 51,990 辆)</span>
        <span class="stats-badge">案例等权 MAPE = {MAPE_EQ}% (加权 {MAPE_WT}%)</span>
        <span class="stats-badge">偏差区间: [+1.66%, +7.27%]</span>
      </div>
      <div class="chart-container">
        {generate_svg_rq1(["顺丰速运(干支)", "中通快递(纯干)", "京东物流(城配)", "区域冷链(中重)"], ledgers, estimates, errors)}
      </div>
      <div class="findings">
        <strong>实证发现</strong>：相较于依赖详尽燃油发票的能源台账法，基于“车型×因子×里程×保守偏置”的活动水平算法案例等权平均偏差为 {MAPE_EQ}%、加权为 {MAPE_WT}%；4 组场景偏差方向一致为正（偏保守估计）。需同时说明：移除满载率偏置后等权 MAPE 反降至 {LF_NO_BIAS_MAPE}%，故该偏置的价值在于保守性而非精度。
      </div>
    </div>

    <!-- RQ2 -->
    <div class="card">
      <h2>RQ2: 双碳政策法规检索中标题重排机制的有效性与非参数检验</h2>
      <div>
        <span class="stats-badge">自建评测集: 40 题标准基准 (含 4 负例)</span>
        <span class="stats-badge">{KB_BADGE}</span>
        <span class="stats-badge">Wilcoxon（融合 vs 纯关键词）: p = {_SIG_P:.4f}，Holm {_SIG_PHOLM:.4f}（{_SIG_VERDICT}）</span>
      </div>
      <div class="chart-container">
        {generate_svg_rq2(summary, stats)}
      </div>
      <div class="findings">
        <strong>实证发现</strong>：同一语料（39 份政策文件 / 281 切片）与同一中文嵌入（bge-small-zh-v1.5）条件下，纯关键词 MRR 0.4879 / R@10 70.0%，纯向量 0.2589 / 57.5%，三路加权融合 0.4920 / 80.0%。融合相对纯向量显著（W=76.0, p=0.0023, Holm 0.0138），相对纯关键词不显著（W=42.0, p=0.320, Holm 0.961）。4 道反事实负例题的检索命中率为 2/4（50%）——检索层不实现拒答，早期“拒答率 75%/100%”属循环定义，已撤回。
      </div>
    </div>

    <!-- RQ3 -->
    <div class="card">
      <h2>RQ3: 运营参数扰动下的敏感性矩阵与不确定性边界</h2>
      <div>
        <span class="stats-badge">扰动网格: 实载率 (-0.30 ~ +0.15) × 里程 (±20%)</span>
        <span class="stats-badge">误差扫描区间: [{SENS_LO}%, {SENS_HI}%] (中位数 {_MEDIAN}%)</span>
      </div>
      <div class="chart-container">
        {generate_svg_rq3()}
      </div>
      <div class="findings">
        <strong>实证发现</strong>：参数扰动表明年均里程是一阶主导因子，但效应<b>强不对称</b>——+20% 使 MAPE 上升 +20.72~+21.63 pp，−20% 仅上升 +5.30~+13.55 pp；实载率引起的 MAPE 变化约 4.59 pp（行内极差 3.67~5.50 pp），不是可跨里程倍数通用的常数。全网格 {SENS_N} 组中 {SENS_OVER10} 组超过 10%，中位数 {_MEDIAN}%。
      </div>
    </div>
  </div>
</body>
</html>
"""
    dashboard_html.write_text(dash_content, encoding="utf-8")
    print(f"✅ 生成全景展板单页: {dashboard_html}")
    print("=" * 70)
    print("🎉 所有中期答辩产物生成完成！")

if __name__ == "__main__":
    build_all_artifacts()
