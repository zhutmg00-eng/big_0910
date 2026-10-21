# 已知缺口与未实现承诺（Known Gaps）

本文件逐条登记「材料声称 / 代码承诺」与「实际实现」之间的差异。
每条都标注**当前状态**与**可复现的验证方式**，用于答辩现场被追问时直接引用，
也用于防止后续迭代把未实现的能力写成已完成。

> 维护约定：新增缺口必须在这里登记，并在 `tests/test_claim_consistency.py`
> 里加一条守卫测试；缺口修好后，把状态改为「已修复」并保留原文（可追溯）。

---

## GAP-1 `/api/turnover` —— 插件与 CLI 声明了，HTTP 层未实现（已修复）

- **声称位置**：`packages/dsh-plugin-carbon-asset/src/index.ts:346`
  `bridge.execute('/api/turnover', 'turnover', args)`，
  工具名 `carbon_turnover_evaluate`（周转量碳强度评估）。
- **历史状态**：FastAPI 应用此前未注册该路由，实测 `POST /api/turnover` 报 404，
  依赖 CLI 降级通道运行。
- **现已修复**：新建 `src/api/routes_turnover.py` 并在 `src/api/main.py` 挂载
  `POST /api/turnover`，输入输出对齐插件 Schema，复用 `src/engine/indirect_emission.py`
  的计算函数，并提供针对输入边界与鉴权的测试 `tests/test_api_turnover.py`。
- **状态**：**已修复**（HTTP 接口与 CLI 桥接完全一致，共用底层计算引擎）。

## GAP-2 未实现 MCP server

- **实际状态**：项目交付的是 DeepSeek Harness 插件
  （`packages/dsh-plugin-carbon-asset`，注册 6 个工具），**没有** MCP server。
- **含义**：不能声称「支持 MCP 协议」或「可接入任意支持 MCP 的宿主」。
  对外只应写「按 DeepSeek Harness 插件规范封装 6 个工具」。
- **状态**：非缺陷，属**能力边界说明**，已在 README 与论文措辞中限定。

## GAP-3 知识库是运行时产物，克隆后为空

- `data/chroma_db/` 被 `.gitignore` 排除，`git clone` 后政策问答返回空。
- 必须执行 `python scripts/ingest_policy_docs.py --force`（39 份 / 281 块，约 13–22 s，
  首次另需约 90 MB 的 `BAAI/bge-small-zh-v1.5` 模型）。
- 自检：`GET /api/kb/health`，空库或换嵌入模型导致的「静默空库」会被检出。
- **状态**：设计如此，README「冷启动」小节已说明。

## GAP-4 案例外部效度：验证集是「有台账的企业」

- 四个实证案例（顺丰、中通、京东、区域冷链）都是披露了燃料台账的头部企业，
  而项目诉求是服务「无台账的中小车队」——**验证集与目标用户不是同一群体**。
- 同时 `derived_baseline_from_ledger_tco2e` 是「披露燃料量 × 项目自身因子」的
  **复算基准**，不是企业原始披露值；因此 4.23% 是**内部一致性**指标，
  不是对第三方披露值的独立验证。
- **状态**：设计限制，已写入论文 5.x、`docs/real_fleet_validation_report.md` 与
  `data/raw/real_fleets/sources_and_methodology.md` 第五节。

## GAP-5 RAG 评测集规模 n=40、且自建自测

- 40 题金标集由课题组自行标注，两轮标注在定稿后完成（一致性复核而非盲标），
  取值零变异导致 Cohen's κ 数学退化为 1，**不能**作为信度证据。
- 负例题仅 4 道，分辨率 25 个百分点；组 C 相对组 A 的 MRR 差 0.0041，
  Wilcoxon W=42.0、p=0.3203、Holm 校正后 0.9608，**不显著**；
  真实增量在 Recall@10（80.00% vs 70.00%，+10 pp = 4 道题）。
- **状态**：已如实报告，并在论文摘要、答辩材料中作为局限声明。
