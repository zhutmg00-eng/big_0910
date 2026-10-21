#!/usr/bin/env python3
"""生成系统技术架构全景矢量图。

图上的所有数字都必须现取，不能手抄：
- 测试总数：运行时 `pytest --collect-only` 收集到的条数（本轮从 248 更正为实时值）；
- MRR 与显著性：docs/rag_benchmark/rag_retrieval_experiment_results.json 的 rrf3 段。
历史事故：fig0 曾长期印着「全量 248 项自动化测试全部通过」（真实值是它的 1.6 倍）
与「MRR 0.5036 (Wilcoxon p &lt; 0.001***)」（v0.3 遗留值，实测 0.4920 且不显著）。
"""
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
svg_path = ROOT / "docs" / "artifacts" / "fig0_system_architecture.svg"


def _collected_test_count() -> int:
    """取运行时真实收集到的测试条数；失败时返回 0，让图上的说明自动降级。"""
    try:
        out = subprocess.run(
            [sys.executable, "-m", "pytest", "--collect-only", "-q", "--ignore=tmp"],
            cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=300,
        ).stdout
    except Exception:
        return 0
    match = re.search(r"(\d+)\s+tests?\s+collected", out)
    return int(match.group(1)) if match else 0


def _rag_headline() -> tuple[str, str]:
    """取 rrf3 的 MRR 与相对纯关键词的 Holm 校正 p 值。"""
    path = ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return "MRR 见评测报告", "显著性见评测报告"
    mrr = payload["summary_metrics"]["rrf3"]["MRR"]
    sig = payload.get("statistical_significance", {}).get("rrf3_vs_keyword", {})
    p_holm = sig.get("p_holm")
    if p_holm is None:
        return f"MRR {mrr:.4f}", "Holm 校正见报告"
    verdict = "显著" if p_holm < 0.05 else "不显著"
    return f"MRR {mrr:.4f}", f"vs 纯关键词 Holm={p_holm:.4f}（{verdict}）"


TEST_COUNT = _collected_test_count()
RAG_MRR_TEXT, RAG_SIG_TEXT = _rag_headline()
TEST_LINE = (
    f"工程规范：全仓本地环境运行 | 全量 {TEST_COUNT} 项自动化测试（运行时收集）"
    if TEST_COUNT
    else "工程规范：全仓本地环境运行 | 测试数以运行时收集为准 | 严格遵循情景模拟与非纳管边界"
)
svg_path.parent.mkdir(parents=True, exist_ok=True)

INK = '#1a2521'
MUTED = '#55645d'
GRID = '#e2e8e5'
GREEN = '#1e6b4b'
BLUE = '#2f6fa3'
AMBER = '#c07c2a'
TEAL = '#2b7570'

svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1000 520" width="100%" height="100%" style="background:#ffffff; font-family:'Segoe UI', 'PingFang SC', 'Microsoft YaHei', sans-serif;">
  <rect width="1000" height="520" fill="#fcfdfc" rx="10"/>
  <text x="40" y="42" font-size="20" font-weight="bold" fill="{INK}">物流碳排放与减排情景决策助手 ─ 系统全层级技术架构图</text>
  <text x="40" y="66" font-size="13" fill="{MUTED}">双模接入层 (FastAPI / DSH Plugin) ── 核心计算推理引擎 ── 科学问题实证支撑基准</text>

  <!-- 第 1 层: 用户与接入层 -->
  <rect x="40" y="90" width="920" height="80" fill="#f4f8f6" stroke="{GRID}" rx="8"/>
  <text x="55" y="115" font-size="13" font-weight="bold" fill="{GREEN}">【接入与呈现层 (Access &amp; Presentation)】</text>
  
  <rect x="230" y="108" width="210" height="48" fill="#ffffff" stroke="{BLUE}" rx="6"/>
  <text x="335" y="130" font-size="12" font-weight="600" fill="{INK}" text-anchor="middle">FastAPI 异步微服务</text>
  <text x="335" y="146" font-size="10" fill="{MUTED}" text-anchor="middle">/calculate, /tco, /ask, /compare</text>

  <rect x="460" y="108" width="230" height="48" fill="#ffffff" stroke="{GREEN}" rx="6"/>
  <text x="575" y="130" font-size="12" font-weight="600" fill="{INK}" text-anchor="middle">DeepSeek Harness 生态插件</text>
  <text x="575" y="146" font-size="10" fill="{MUTED}" text-anchor="middle">dsh-plugin-carbon-asset (6大Tools)</text>

  <rect x="710" y="108" width="230" height="48" fill="#ffffff" stroke="{AMBER}" rx="6"/>
  <text x="825" y="130" font-size="12" font-weight="600" fill="{INK}" text-anchor="middle">GenUI / HTML 自包含展板</text>
  <text x="825" y="146" font-size="10" fill="{MUTED}" text-anchor="middle">全交互可视化实证看板 (无流式挂起)</text>

  <!-- 连线箭头 1 -->
  <line x1="500" y1="170" x2="500" y2="195" stroke="{MUTED}" stroke-width="2"/>

  <!-- 第 2 层: 核心业务引擎层 -->
  <rect x="40" y="195" width="920" height="140" fill="#ffffff" stroke="{GRID}" rx="8"/>
  <text x="55" y="220" font-size="13" font-weight="bold" fill="{BLUE}">【核心模型与计算引擎层 (Core Engines)】</text>

  <rect x="60" y="235" width="200" height="85" fill="#f8faf9" stroke="{GRID}" rx="6"/>
  <text x="160" y="258" font-size="12" font-weight="bold" fill="{INK}" text-anchor="middle">基线核算与满载惩罚</text>
  <text x="160" y="278" font-size="11" fill="{MUTED}" text-anchor="middle">自下而上活动水平法</text>
  <text x="160" y="296" font-size="10" fill="{GREEN}" text-anchor="middle">LF = 1 + 0.15*(0.75 - l_i)</text>

  <rect x="280" y="235" width="210" height="85" fill="#f8faf9" stroke="{GRID}" rx="6"/>
  <text x="385" y="258" font-size="12" font-weight="bold" fill="{INK}" text-anchor="middle">情景模拟与 TCO 联动</text>
  <text x="385" y="278" font-size="11" fill="{MUTED}" text-anchor="middle">纯电替代 / 满载率提升</text>
  <text x="385" y="296" font-size="10" fill="{GREEN}" text-anchor="middle">回收期 / MAC / 物理守恒</text>

  <rect x="510" y="235" width="210" height="85" fill="#f8faf9" stroke="{GRID}" rx="6"/>
  <text x="615" y="258" font-size="12" font-weight="bold" fill="{INK}" text-anchor="middle">Scope 2 外购电与周转量</text>
  <text x="615" y="278" font-size="11" fill="{MUTED}" text-anchor="middle">2025年47号公告30省因子</text>
  <text x="615" y="296" font-size="10" fill="{GREEN}" text-anchor="middle">万吨公里 / gCO2/t·km强度</text>

  <rect x="740" y="235" width="200" height="85" fill="#f8faf9" stroke="{GRID}" rx="6"/>
  <text x="840" y="258" font-size="12" font-weight="bold" fill="{INK}" text-anchor="middle">垂直领域 RAG 检索</text>
  <text x="840" y="278" font-size="11" fill="{MUTED}" text-anchor="middle">39份政策文件281块入库定块</text>
  <text x="840" y="296" font-size="10" fill="{GREEN}" text-anchor="middle">向量初筛 + 领域词重排</text>

  <!-- 连线箭头 2 -->
  <line x1="500" y1="335" x2="500" y2="360" stroke="{MUTED}" stroke-width="2"/>

  <!-- 第 3 层: 科学问题与实证证据链层 -->
  <rect x="40" y="360" width="920" height="125" fill="#f0f7f4" stroke="{GREEN}" rx="8"/>
  <text x="55" y="385" font-size="13" font-weight="bold" fill="{GREEN}">【科研问题实证支撑体系 (Empirical Evidence for RQs)】</text>

  <rect x="60" y="398" width="270" height="72" fill="#ffffff" stroke="{GRID}" rx="6"/>
  <text x="195" y="418" font-size="12" font-weight="bold" fill="{BLUE}" text-anchor="middle">RQ1: 真实车队基准检验</text>
  <text x="195" y="438" font-size="11" fill="{MUTED}" text-anchor="middle">顺丰/中通/京东/冷链 51,990 辆台账</text>
  <text x="195" y="456" font-size="11" font-weight="bold" fill="{GREEN}" text-anchor="middle">等权 MAPE 4.23% (加权 2.38%)</text>

  <rect x="365" y="398" width="270" height="72" fill="#ffffff" stroke="{GRID}" rx="6"/>
  <text x="500" y="418" font-size="12" font-weight="bold" fill="{BLUE}" text-anchor="middle">RQ2: 40题基准集与检索检验</text>
  <text x="500" y="438" font-size="11" fill="{MUTED}" text-anchor="middle">40 题自建基准集 (含4负例，双人独立审校)</text>
  <text x="500" y="456" font-size="11" font-weight="bold" fill="{GREEN}" text-anchor="middle">{RAG_MRR_TEXT}（三路加权融合）</text>
  <text x="500" y="470" font-size="9" fill="{MUTED}" text-anchor="middle">{RAG_SIG_TEXT}</text>

  <rect x="670" y="398" width="270" height="72" fill="#ffffff" stroke="{GRID}" rx="6"/>
  <text x="805" y="418" font-size="12" font-weight="bold" fill="{BLUE}" text-anchor="middle">RQ3: 参数扰动敏感性网格</text>
  <text x="805" y="438" font-size="11" fill="{MUTED}" text-anchor="middle">实载率 (-0.3~+0.15) × 里程 (±20%)</text>
  <text x="805" y="456" font-size="11" font-weight="bold" fill="{GREEN}" text-anchor="middle">50组扫描：3.04% ~ 29.80%</text>

  <!-- 底部规范声明 -->
  <text x="500" y="505" font-size="11" fill="{MUTED}" text-anchor="middle">{TEST_LINE} | 严格遵循情景模拟与非纳管边界</text>
</svg>'''

svg_path.write_text(svg, encoding="utf-8")
print(f"System architecture SVG created: {svg_path}")
