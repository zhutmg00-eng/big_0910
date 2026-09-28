# 物流双碳政策问答标准化评测集 (RAG Benchmark)

> 本数据集为大创项目“物流碳排放与减排情景决策助手”课题组自主研发的面向中国碳市场法规与绿色交通政策的标准问答基准集。

## 评测集概述
- **题目规模**：精选 40 道覆盖六大核心政策维度的问答题（含金标答案、所属官方文件、适用性标签及负例拒答设计）。
- **主题覆盖**：
  1. 全国碳市场配额分配与行业扩围（Q01–Q08）
  2. 顶层条例、管理办法与效力层级（Q09–Q13）
  3. 排放监测、报告与核查 (MRV) 及购电口径（Q14–Q19）
  4. 国家核证自愿减排量 (CCER) 与额外性机制（Q20–Q25）
  5. 地方碳市场试点与行业纳入门槛（Q26–Q31）
  6. 绿色交通专项规划与车辆能耗限值标准（Q32–Q40）

## 目录结构
- `rag_eval_framework.md`：评测集构建方案、题型分布、双人标注规范与评价指标（Recall@k、MRR、引用保真度、适用范围准确率）。
- `rag_benchmark_40_questions.md`：40 题完整题库（含标准参考答案要点与检索文件定位）。
- `rag_benchmark_gold_dataset.json` / `rag_benchmark_gold_dataset.csv`：40 题标准金标数据集（已完成与全量 268 个 Chunk 的唯一 gold_chunk_ids 精准定块映射）。
- `rag_retrieval_experiment_report.md`：纯关键词 vs 纯向量 vs 混合重排 三组检索对照实验评估报告（含 Wilcoxon 符号秩显著性检验）。
- `rag_retrieval_experiment_results.json`：评测实验全量详细指标与各题召回数据。
- `review/`：标注者 A 与标注者 B 的双人独立审校标注表与一致性报告（Kappa = 1.0）。
- `parts/`：按主题细分的子集模块。
