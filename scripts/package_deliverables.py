#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""大创中期成果汇报打包脚本：供上交指导教师审查的全套材料。

严格排除：
- docs/中期待办与导师沟通要点.md (私下准备材料)
- 任何 .git, .venv, tmp, __pycache__, .bak 文件
- 临时性开发脚本与草稿

产物：
- 目录：output/大创中期成果汇报材料_物流碳决策助手_202610/
- 压缩包：output/大创中期成果汇报材料_物流碳决策助手_202610.zip
"""
import os
import shutil
import sys
import zipfile
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parent.parent
OUTPUT_BASE = ROOT / "output"
PKG_DIR = OUTPUT_BASE / "大创中期成果汇报材料_物流碳决策助手_202610"
ZIP_PATH = OUTPUT_BASE / "大创中期成果汇报材料_物流碳决策助手_202610.zip"


def copy_file(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    print(f"  + {dst.relative_to(PKG_DIR)}")


def copy_dir(src: Path, dst: Path, ignore_patterns=None):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "*.pyo", ".git*", ".pytest_cache", "*.log",
        *(ignore_patterns or [])
    ))
    print(f"  + [DIR] {dst.relative_to(PKG_DIR)} ({len(list(dst.rglob('*')))} items)")


def main():
    if PKG_DIR.exists():
        shutil.rmtree(PKG_DIR)
    PKG_DIR.mkdir(parents=True, exist_ok=True)

    print("=" * 80)
    print("📦 开始打包大创中期成果汇报全套材料...")
    print("=" * 80)

    # -------------------------------------------------------------
    # 00_成果总览与阅读指引
    # -------------------------------------------------------------
    guide_md = """# 物流碳排放与减排情景决策助手 · 大创中期成果全套材料阅读指引

**项目名称**：数据驱动的物流车队碳排放微观测算与情景决策支持系统（`carbon-assistant`）  
**指导教师**：汪晓霞 教授  
**团队成员**：陈铭浩（负责人 / 架构）、张可为（算法 / 实证）、王逸贤（工程 / 评测）  
**汇报阶段**：国家级大学生创新创业训练计划科研项目 · 2026 年 10 月中期检查  

---

## 文件夹目录导航

尊敬的汪老师：

团队已完成大创中期研发攻关、实证台账复核、政策评测集构建与工程系统落地。本资料包已按规范体系分类归档，建议按以下顺序审阅：

### 📁 01_学术论文与中期报告（核心文书）
- **`学术论文_数据驱动的物流车队碳排放微观测算与情景决策支持系统.pdf`**：33 页标准出版级期刊格式论文（含完整摘要、机理公式推导、四大真实车队实证复核、两阶段混合重排算法、参数扰动敏感性、30个省级行政区电网判据分析与29篇权威参考文献）。
- **`学术论文_初稿手稿.md`**：论文 Markdown 原始源文件。
- **`大创中期进展说明书_技术与实证全景.pdf`** / **`.md`**：系统阐述“做了什么、遇到什么问题、如何解决以及后续计划”的核心技术进展说明书。
- **`大创中期答辩核心指南与评审问辨应对.pdf`**：答辩策略、评委关注点梳理与 12 大关键质询应答手册。
- **`大创中期答辩成果与实证全景报告.md`**：围绕 RQ1、RQ2、RQ3 展开的完整科研实证实验总结报告。
- **`开题报告.md`** 与 **`文献综述.md`**：前期立项与文献梳理归档。

### 📁 02_答辩PPT与可视化展板（展示与汇报成果）
- **`大创中期答辩汇报_物流碳决策助手.pptx`**：16:9 白底深蓝学术风格答辩幻灯片（共 16 页，涵盖选题痛点、科学问题树、技术架构、实证图表、BaaS决策与经费执行）。
- **`全景科研实证交互展板_all_charts_dashboard.html`**：自包含单页实证展板（双击即可在浏览器全交互查看 RQ1/RQ2/RQ3 图表）。
- **`答辩演练网页展板_defense_presentation_deck.html`**：配有逐页 30~45 秒实战讲稿与交互卡片的幻灯片网页版。
- **`核心学术图表/`**：`fig0` ~ `fig5` 共 6 组 300 DPI 高清学术图表（PNG 与矢量 SVG 双格式）：
  - `fig0_系统三层技术架构`
  - `fig1_车队基准复核相对偏差`
  - `fig2_RAG三组检索对照实验`
  - `fig3_参数扰动敏感性矩阵热力图`
  - `fig4_BaaS车电分离TCO经济性对标`
  - `fig5_30个省级行政区电网因子与判据阈值`

### 📁 03_实证数据与分析台账（单一事实源）
- **`全指标标准数据台账_derived_metrics.json`**：全仓论文、报告、PPT 所有引用的唯一数字来源（一键重新派生）。
- **`真实车队台账一致性核验_fleet_ledger_consistency.json`**：顺丰、中通、京东、冷链 4 组车队等效能耗比值（0.93~1.11）与单车反推百公里油耗合理性核验。
- **`TCO电价与里程敏感性分析报告_tco_sensitivity_report.md`**：充换电单价 × 年里程对 BaaS 回收期影响的双向敏感性网格。
- **`车队实证复核报告_real_fleet_validation_report.md`**：51,990 辆车队级基准案例复核详细报告（等权 MAPE 4.23%、加权 2.38%）。
- **`参数扰动敏感性报告_sensitivity_report.md`**：50 组参数扰动网格扫描报告（3.04% ~ 29.80%，中位数 14.52%）。
- **`真实车队原始数据集/`**：涵盖顺丰、中通、京东、冷链公开 ESG 报告数据的 `benchmark_fleets.json` 与 `benchmark_fleets.csv`。

### 📁 04_双碳政策RAG知识库与评测集（知识推理成果）
- **`双碳政策40题标准金标评测集.json`** / **`.csv`**：涵盖 6 大政策维度的评测题库，每题均与 37 份法规的 268 个规范 Chunk 严格绑定。
- **`反事实合规负例30题评测集.json`** / **`.md`**：专门考核系统防幻觉、合规拒答能力的 30 道负例基准。
- **`RAG检索实验评估报告_rag_retrieval_experiment_report.md`**：纯关键词、纯向量、混合重排三组检索对比与 Wilcoxon 非参数统计检验。
- **`向量嵌入检索诊断报告_embedding_diagnostic.json`**：量化默认嵌入在中文法律文本上的区分度测量与诊断分析。
- **`评测集双人独立审校一致性报告.md`**：评测集交叉审校报告。

### 📁 05_系统源代码与工程规范（代码资产）
- **`src/`**：包含直接运营排放核算引擎、TCO/BaaS 模型、Scope 2 电网因子与周转量强度引擎、RAG 向量检索管线、FastAPI 微服务与 Streamlit 交互前端。
- **`tests/`**：包含全量 **117 项自动化回归测试**，本地已全部验证通过（100% 绿灯）。
- **`scripts/`**：包含数据派生 (`gen_derived_metrics.py`)、台账一致性核验 (`check_fleet_ledger_consistency.py`)、TCO 敏感性分析 (`tco_sensitivity.py`)、图表渲染等全套科研复现脚本。
- **`packages/dsh-plugin-carbon-asset/`**：DeepSeek Harness 官方微内核生态插件源码（注册 6 项专业工具，支持 HTTP / 本地 CLI 降级双模）。
- **`README.md`** 与 **`系统架构设计说明_architecture.md`**：完整的工程部署与技术说明。

---

## 核心科研指标一览（汇报答辩快速对标）

1. **车队实证复核**：覆盖 4 组代表性车队、合计 **51,990 辆**规模；模型估算值与燃料台账复算基准的绝对相对偏差严格在 $\pm 8\%$ 以内，**案例等权 MAPE 为 4.23%、排放加权为 2.38%**；四组场景误差方向一致为正，符合国际气候披露准则 (GHG Protocol) 的保守性测算原则。
2. **法规 RAG 检索**：在自建 40 题标准评测集上，混合重排引擎政策源文件命中率 Source-Hit@3 达 **80.0%**，MRR 达 0.5036，较纯向量检索取得统计学极显著跃升（Wilcoxon 检验 $p < 0.001$）；在反事实负例合规拒答上表现稳健。
3. **电网因子与判据**：联动生态环境部 2025 年第 47 号公告 **30 个省级行政区**最新电网因子；推导出以电代油临界碳强度阈值（重卡 0.5847、轻卡 1.0686 kgCO₂/kWh），揭示了华北西北 10 个火电高占比省份在未配置绿电时重卡全流程碳排放反超柴油车的机理。
4. **TCO 经济决策**：构建车电分离 BaaS 财务模型，使 49t 纯电重卡初始垫资降低 69.7%，基准静态回收期由买断的 2.34 年压缩至 1.04 年，并量化了电价上涨与里程缩减对回收期的敏感性边界。
5. **代码质量保证**：全仓 **117 项 pytest 单元测试全部通过**，严格隔离法定碳市场履约，坚守科研情景模拟对标底线。
"""
    (PKG_DIR / "00_成果总览与阅读指引.md").write_text(guide_md, encoding="utf-8")
    print("  + 00_成果总览与阅读指引.md")

    # -------------------------------------------------------------
    # 01_学术论文与报告
    # -------------------------------------------------------------
    print("\n[1/5] 归档学术论文与报告...")
    copy_file(ROOT / "docs" / "artifacts" / "academic_paper.pdf",
              PKG_DIR / "01_学术论文与报告" / "学术论文_数据驱动的物流车队碳排放微观测算与情景决策支持系统.pdf")
    copy_file(ROOT / "docs" / "academic_paper.md",
              PKG_DIR / "01_学术论文与报告" / "学术论文_手稿正文.md")
    copy_file(ROOT / "docs" / "artifacts" / "大创中期进展说明书_技术与实证全景.pdf",
              PKG_DIR / "01_学术论文与报告" / "大创中期进展说明书_技术与实证全景.pdf")
    copy_file(ROOT / "docs" / "artifacts" / "大创中期答辩核心指南与评审问辨应对.pdf",
              PKG_DIR / "01_学术论文与报告" / "大创中期答辩核心指南与评审问辨应对.pdf")
    copy_file(ROOT / "docs" / "大创中期进展说明书_技术与实证全景.md",
              PKG_DIR / "01_学术论文与报告" / "大创中期进展说明书_技术与实证全景.md")
    copy_file(ROOT / "docs" / "中期答辩成果与实证全景报告.md",
              PKG_DIR / "01_学术论文与报告" / "大创中期答辩成果与实证全景报告.md")
    copy_file(ROOT / "docs" / "开题报告.md",
              PKG_DIR / "01_学术论文与报告" / "开题报告.md")
    copy_file(ROOT / "docs" / "literature_review.md",
              PKG_DIR / "01_学术论文与报告" / "文献综述.md")
    copy_file(ROOT / "docs" / "academic_paper_review.md",
              PKG_DIR / "01_学术论文与报告" / "论文取证式一致性审计报告.md")
    copy_file(ROOT / "docs" / "academic_paper_revision_notes.md",
              PKG_DIR / "01_学术论文与报告" / "论文修订对照说明.md")

    # -------------------------------------------------------------
    # 02_答辩PPT与可视化展板
    # -------------------------------------------------------------
    print("\n[2/5] 归档答辩PPT与可视化展板...")
    copy_file(ROOT / "docs" / "大创中期答辩汇报_物流碳决策助手.pptx",
              PKG_DIR / "02_答辩PPT与可视化展板" / "大创中期答辩汇报_物流碳决策助手.pptx")
    copy_file(ROOT / "docs" / "artifacts" / "all_charts_dashboard.html",
              PKG_DIR / "02_答辩PPT与可视化展板" / "全景科研实证交互展板.html")
    copy_file(ROOT / "docs" / "artifacts" / "defense_presentation_deck.html",
              PKG_DIR / "02_答辩PPT与可视化展板" / "答辩演练网页展板.html")
    copy_file(ROOT / "docs" / "artifacts" / "academic_paper_preview.html",
              PKG_DIR / "02_答辩PPT与可视化展板" / "论文网页预览版.html")

    fig_map = [
        ("fig0_system_architecture", "fig0_系统三层技术架构"),
        ("fig1_rq1_real_fleet_validation", "fig1_车队基准复核相对偏差"),
        ("fig2_rq2_rag_benchmark_comparison", "fig2_RAG三组检索对照实验"),
        ("fig3_rq3_sensitivity_heatmap", "fig3_参数扰动敏感性矩阵热力图"),
        ("fig4_baas_tco_comparison", "fig4_BaaS车电分离TCO经济性对标"),
        ("fig5_grid_scope2_green_power", "fig5_30个省级行政区电网因子与判据阈值"),
    ]
    for src_stem, dst_stem in fig_map:
        for ext in ("png", "svg"):
            src_f = ROOT / "docs" / "artifacts" / f"{src_stem}.{ext}"
            if src_f.exists():
                copy_file(src_f, PKG_DIR / "02_答辩PPT与可视化展板" / "核心学术图表" / f"{dst_stem}.{ext}")

    # -------------------------------------------------------------
    # 03_实证数据与分析台账
    # -------------------------------------------------------------
    print("\n[3/5] 归档实证数据与分析台账...")
    copy_file(ROOT / "docs" / "derived_metrics.json",
              PKG_DIR / "03_实证数据与分析台账" / "全指标标准数据台账_derived_metrics.json")
    copy_file(ROOT / "docs" / "fleet_ledger_consistency.json",
              PKG_DIR / "03_实证数据与分析台账" / "车队台账等效能耗一致性核验_fleet_ledger_consistency.json")
    copy_file(ROOT / "docs" / "tco_sensitivity_report.md",
              PKG_DIR / "03_实证数据与分析台账" / "TCO电价与里程敏感性分析报告.md")
    copy_file(ROOT / "docs" / "real_fleet_validation_report.md",
              PKG_DIR / "03_实证数据与分析台账" / "车队实证复核报告.md")
    copy_file(ROOT / "docs" / "sensitivity_report.md",
              PKG_DIR / "03_实证数据与分析台账" / "参数扰动敏感性报告.md")
    copy_dir(ROOT / "data" / "raw" / "real_fleets",
             PKG_DIR / "03_实证数据与分析台账" / "真实车队原始数据集")
    copy_file(ROOT / "data" / "raw" / "emission_factors.csv",
              PKG_DIR / "03_实证数据与分析台账" / "车辆排放因子基础库.csv")
    copy_file(ROOT / "data" / "raw" / "carbon_price_history.csv",
              PKG_DIR / "03_实证数据与分析台账" / "全国碳市场历史价格数据.csv")

    # -------------------------------------------------------------
    # 04_双碳政策RAG知识库与评测集
    # -------------------------------------------------------------
    print("\n[4/5] 归档双碳政策RAG知识库与评测集...")
    copy_file(ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.json",
              PKG_DIR / "04_双碳政策RAG知识库与评测集" / "双碳政策40题标准金标评测集.json")
    copy_file(ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.csv",
              PKG_DIR / "04_双碳政策RAG知识库与评测集" / "双碳政策40题标准金标评测集.csv")
    copy_file(ROOT / "docs" / "rag_benchmark" / "negative_benchmark_30_questions.json",
              PKG_DIR / "04_双碳政策RAG知识库与评测集" / "反事实合规负例30题评测集.json")
    copy_file(ROOT / "docs" / "rag_benchmark" / "negative_benchmark_30_questions.md",
              PKG_DIR / "04_双碳政策RAG知识库与评测集" / "反事实合规负例30题评测集说明.md")
    copy_file(ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_report.md",
              PKG_DIR / "04_双碳政策RAG知识库与评测集" / "RAG检索实验评估报告.md")
    copy_file(ROOT / "docs" / "embedding_diagnostic.json",
              PKG_DIR / "04_双碳政策RAG知识库与评测集" / "向量嵌入检索名次与距离差诊断报告.json")
    copy_file(ROOT / "docs" / "rag_benchmark" / "review" / "双人独立审校一致性报告.md",
              PKG_DIR / "04_双碳政策RAG知识库与评测集" / "评测集双人独立审校一致性报告.md")

    # -------------------------------------------------------------
    # 05_系统源代码与工程规范
    # -------------------------------------------------------------
    print("\n[5/5] 归档系统源代码与工程规范...")
    copy_dir(ROOT / "src", PKG_DIR / "05_系统源代码与工程规范" / "src")
    copy_dir(ROOT / "tests", PKG_DIR / "05_系统源代码与工程规范" / "tests")
    copy_dir(ROOT / "scripts", PKG_DIR / "05_系统源代码与工程规范" / "scripts",
             ignore_patterns=["*paper*", "*academic*"])
    copy_dir(ROOT / "packages", PKG_DIR / "05_系统源代码与工程规范" / "packages")
    copy_file(ROOT / "README.md", PKG_DIR / "05_系统源代码与工程规范" / "README.md")
    copy_file(ROOT / "docs" / "architecture.md",
              PKG_DIR / "05_系统源代码与工程规范" / "系统架构设计说明.md")
    copy_file(ROOT / "requirements.txt",
              PKG_DIR / "05_系统源代码与工程规范" / "requirements.txt")

    # -------------------------------------------------------------
    # 打包为 ZIP
    # -------------------------------------------------------------
    print("\n" + "=" * 80)
    print("🗜️  正在压缩打包为 ZIP 文件...")
    if ZIP_PATH.exists():
        ZIP_PATH.unlink()

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for file_path in PKG_DIR.rglob("*"):
            if file_path.is_file():
                arcname = file_path.relative_to(OUTPUT_BASE)
                zf.write(file_path, arcname)

    zip_size_mb = ZIP_PATH.stat().st_size / (1024 * 1024)
    print(f"🎉 打包完成！")
    print(f"📁 成果文件夹: {PKG_DIR}")
    print(f"📦 成果压缩包: {ZIP_PATH} ({zip_size_mb:.2f} MB)")
    print("=" * 80)


if __name__ == "__main__":
    main()
