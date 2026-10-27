# 物流碳排放与减排情景决策助手

> 面向物流运输企业的大学生创新训练科研原型：直接运营排放核算、减排情景分析与政策资料检索。

## 项目定位

本项目输入车型、车辆数、年均里程和满载率，输出车辆直接运营排放基线，并通过模拟碳预算比较不同减排情景。政策助手使用本地政策知识库检索相关原文；配置 LLM 后可在检索内容范围内生成分析，未配置时返回带来源的原文摘录。

本项目适合作为大创项目的前提，是将研究重点放在“物流企业排放核算与政策检索方法验证”，而不是宣称已经提供法定碳资产管理或履约服务。

> 重要边界：物流运输行业目前未纳入全国碳市场配额管理。系统中的模拟碳预算、预算差额、情景成本和潜在价值仅用于科研比较，不代表法定配额、履约义务、可交易资产或实际收益。新能源物流车当前仅按直接运营排放为零核算，未计购电间接排放及车辆全生命周期排放。

## 当前功能

> v0.4（2026-10 中期优化）新增：中文 BGE 嵌入 + jieba BM25 + RRF 多路融合检索、蒙特卡洛排放不确定性分析、证据溯源展示、「方法与验证」页、ruff+覆盖率 CI。详见 `docs/优化说明_v0.4.md`。

- 车队直接运营排放核算，覆盖排放因子表里的全部车型（16 类），可手工逐条添加
- **车队台账批量导入**：上传 Excel 另存的 CSV（或 GBK/分号/制表符分隔的表），列名支持同义词（车型／车辆类型、数量／台数、年均里程／年行驶里程、满载率／实载率），口语车型（重卡／轻卡／牵引车／LNG重卡…）自动映射到规范名，同一车型多行按车辆数加权合并；每一处自动纠正都会列出来让你核对
- 蒙特卡洛不确定性分析（IPCC 2006 Approach 2）：P5/P50/P95 区间与方差贡献排序
- 模拟碳预算差额与碳价对标情景
- 新能源替代、满载率提升和组合减排情景
- 三路检索融合：jieba 分词 BM25 + 中文稠密向量（bge-small-zh，ONNX 本地推理）+ 字面规则，RRF 倒数排名融合；可选交叉编码器精排
- 回答附带可溯源证据（来源文件、分块 ID、命中检索器、原文摘录）
- PDF、DOCX、HTML、Markdown、TXT 政策文档解析与网页噪声清洗
- 无 LLM 密钥时的可追溯检索式回答
- FastAPI、Streamlit、PDF 报告、多企业对比和 Docker Compose 部署
- 输入边界校验、API Key、CORS、路径范围校验和自动化测试

## 快速开始

要求 Python 3.10 及以上版本。

```powershell
git clone https://github.com/zhutmg00-eng/big_0910.git carbon-logistics-assistant
cd carbon-logistics-assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python scripts/ingest_policy_docs.py --force   # 首次建库（会自动下载约 90MB 中文嵌入模型）
python -m pytest -q
```

> 国内网络下载模型较慢时，先设置 `$env:HF_ENDPOINT="https://hf-mirror.com"`。

### 冷启动：知识库是运行时产物，不在仓库里

`data/chroma_db/` 被 `.gitignore` 排除，因此 `git clone` 之后**没有**向量库，
政策问答会返回空结果（计算类功能不受影响）。首次使用必须先跑一次入库：

```powershell
python scripts/ingest_policy_docs.py --force
```

- 语料是仓库里的 `data/policy_docs/`（40 份，45 个文件中去掉 5 个非 md 附件），
  入库结果为 **40 份 / 287 块**（2026-10-25 新增《绿色交通发展“十五五”规划》官方解读；RQ2 检索评测仍基于 39 份 / 281 块冻结快照）；耗时约 13–22 秒（不含首次下载约 90MB 嵌入模型）。
- 想省掉这一步，可设 `KB_AUTO_INGEST=1`，服务启动时空库会自动入库（见下方配置表）。
- 不确定库是不是空的，直接查自检接口，不要靠猜：

  ```powershell
  curl http://localhost:8000/api/kb/health
  ```

  返回 `status`（`ok` / `empty` / `degraded`）、`count`、`documents`、
  `embedding_model`、`collection_name`、`other_collections` 与 `warning`。
  `status=empty` 时 `warning` 会直接写出修复命令。

> ⚠️ 换嵌入模型会换 collection 名（`carbon_policy_v5_<模型哈希>`），
> 旧库仍在磁盘上但不会被读回，表现为"库突然空了"。
> `/api/kb/health` 的 `other_collections` 字段就是为了让这种静默失效暴露出来。

启动后端和前端：

```powershell
# 终端 1（必须用 venv 里的解释器；直接敲 uvicorn 可能命中系统里的另一个版本）
python -m uvicorn src.api.main:app --reload --port 8000

# 终端 2
python -m streamlit run src/ui/app.py
```

> ⚠️ 如果终端 1 启动后报 `[Errno 10048]`／`address already in use`，说明 8000 端口
> 被别的程序占着，而 uvicorn 只会打一行日志就退出。此时前端仍能连上那个陌生服务，
> 界面会提示「核算服务返回 404，说明该地址上跑的不是本项目后端」。
> 换端口并让前端跟着改：
>
> ```powershell
> python -m uvicorn src.api.main:app --port 8010
> $env:API_BASE_URL="http://localhost:8010"; python -m streamlit run src/ui/app.py
> ```

- Web：`http://localhost:8501`
- API 文档：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/api/health`（进程存活）／`http://localhost:8000/api/kb/health`（知识库自检）

开发环境不设置 `APP_API_KEY` 时，API 进入无鉴权模式。设置密钥后，前端和请求方都需发送同一 `X-API-Key`。

## Docker

```powershell
# 开发环境，默认使用 dev-key
docker compose up --build

# 生产覆盖配置
Copy-Item .env.example .env
# 修改 .env 中 APP_API_KEY 和 CORS_ORIGINS
docker compose -f docker-compose.yml -f docker-compose.prod.yml up --build -d
```

生产配置要求显式提供 `APP_API_KEY` 和 `CORS_ORIGINS`，并保持 Streamlit XSRF 防护开启。
`docker-compose.prod.yml` 用 `${APP_API_KEY:?...}` 做强制校验，缺变量时 compose 直接报错退出，
不会悄悄以无鉴权状态启动。

> ⚠️ **开发配置不能直接暴露到公网**：`docker-compose.yml` 里 `APP_API_KEY` 的默认值是 `dev-key`，
> 而 `src/api/main.py:87` 在未设该变量时直接跳过鉴权。也就是说用开发配置加内网穿透把 8000 端口
> 映射出去，等于把入库接口 `/api/kb/ingest`、`/api/kb/ingest-all` 和计算接口都公开——任何人都能触发全量重建知识库。
> 对外演示必须走 `docker-compose.prod.yml`。
>
> 想知道当前进程到底处于哪种状态，查 `GET /api/health` 的 `security` 字段：
> `protected`（已配真实密钥）/ `open_dev`（未配置）/ `placeholder_key`（填了 `your-api-key-here`
> 之类的占位值，效果等同未鉴权）。启动日志也会以 WARNING 级别打印同一条结论。

## 环境变量

| 变量 | 用途 | 默认值 |
|---|---|---|
| `APP_API_KEY` | FastAPI 与 Streamlit 间的共享密钥 | 空，开发模式不鉴权；占位值同样视为未配置 |
| `API_BASE_URL` | Streamlit 调用的后端地址 | `http://localhost:8000` |
| `CORS_ORIGINS` | 允许的浏览器来源，逗号分隔 | 本地地址 |
| `LLM_MODEL` | 政策分析模型 | `deepseek-chat` |
| `DEEPSEEK_API_KEY` | DeepSeek 密钥，可选 | 空 |
| `DASHSCOPE_API_KEY` | 通义千问密钥，可选 | 空 |
| `ZHIPU_API_KEY` | 智谱密钥，可选 | 空 |
| `OPENAI_API_KEY` | OpenAI LLM 或 Embedding 密钥，可选 | 空 |
| `EMBEDDING_MODEL` | 嵌入模型 | `auto`（= `fastembed:BAAI/bge-small-zh-v1.5`） |
| `RETRIEVAL_MODE` | 检索模式 | `rrf3` |
| `RERANKER_MODEL` | 交叉编码器精排模型，留空关闭 | 空 |
| `KB_AUTO_INGEST` | 启动时知识库为空则自动入库 | `0`（Compose 中为 `1`） |
| `HF_ENDPOINT` | 模型下载镜像 | 官方 |

`EMBEDDING_MODEL` 可设为 `auto`、`fastembed:<model>`、`chromadb-default`（英文模型，仅作对照）、`openai:text-embedding-3-small` 或 `sentence-transformers:<model>`。

## 项目结构

```text
.
├── data/
│   ├── raw/                    # 排放因子、碳价与研究来源
│   ├── policy_docs/            # 政策 Markdown 文档
│   ├── chroma_db/              # 运行时生成，不提交
│   └── reports/                # 示例及运行时 PDF
├── docs/                       # 架构、文献、开题和审查资料
├── scripts/
│   ├── e2e_demo.py             # 计算链路端到端演示
│   ├── ingest_policy_docs.py   # 政策知识库入库
│   └── test_rag_pipeline.py    # RAG 相关性验收
├── src/
│   ├── api/                    # FastAPI 与多企业对比
│   ├── engine/                 # 排放、预算、碳价和减排引擎
│   ├── models/                 # Pydantic 输入模型
│   ├── rag/                    # 解析、混合检索与生成
├── tests/                      # 自动化测试（pytest -q 查看实际数量）
├── packages/
│   └── dsh-plugin-carbon-asset/ # DeepSeek Harness 官方生态插件
├── Dockerfile
└── docker-compose.yml
```

## 🔌 DeepSeek Harness (dsh) 插件支持

本项目已基于官方 Cordis 微内核封装为符合 [DeepSeek Harness (`dsh`)](https://github.com/deepseek-ai/deepseek-harness) 规范的标准生态插件 **`dsh-plugin-carbon-asset`**（位于 `packages/dsh-plugin-carbon-asset/`）。

### 注册的 Agent 工具列表
- `carbon_calculate`：物流车队直接运营碳排放基线测算与模拟碳预算差额对标
- `carbon_tco_evaluate`：新能源纯电货车替换 TCO 拥有成本、静态投资回收期（年）与减排边际成本（MAC）测算
- `carbon_reduction_scenario`：综合减排情景模拟（新能源替换 + 满载率提升优化）
- `carbon_policy_query`：中国碳市场法规与绿色交通双碳政策智能检索与溯源问答
- `carbon_enterprise_compare`：多物流企业多车队横向碳对标矩阵
- `carbon_turnover_evaluate`：营运货物周转量（万吨公里）与新能源车 Scope 2 外购电间接排放综合对标
### 载入与使用方式
在 DeepSeek Harness 的 `cordis.yml` 中挂载：
```yaml
- name: './packages/dsh-plugin-carbon-asset'
  config:
    apiBaseUrl: 'http://127.0.0.1:8000'
    preferHttp: true
```
或者在 dsh 环境下安装：
```bash
dsh plugin add ./packages/dsh-plugin-carbon-asset
```
> **双模自适应**：插件支持 HTTP 接口与本地 Python CLI (`scripts/cli_bridge.py`) 双通道通信。未启动 FastAPI 服务时，插件自动调用子进程计算引擎，即开即用。

## API

| 方法 | 路径 | 说明 | 鉴权 |
|---|---|---|---|
| GET | `/api/health` | 健康检查 | 否 |
| GET | `/api/vehicle-types` | 支持车型和排放因子 | 是 |
| POST | `/api/calculate` | 直接运营排放、模拟预算和情景成本 | 是 |
| POST | `/api/compare` | 多企业情景对比 | 是 |
| POST | `/api/uncertainty` | 蒙特卡洛排放不确定性分析 | 是 |
| POST | `/api/ask` | 政策检索与问答（含证据溯源） | 是 |
| GET | `/api/kb/stats` | 知识库状态 | 是 |
| GET | `/api/kb/health` | 知识库健康自检（空库/换模型静默失效可检出） | 否 |
| POST | `/api/kb/ingest` | 导入 `data/policy_docs` 内单份文档 | 是 |
| POST | `/api/kb/ingest-all` | 批量导入全部政策文档（幂等） | 是 |
| GET/POST | `/api/tco/*` | 新能源替换 TCO 与回收期 | 是 |

无效车辆数、里程、满载率、企业名、空车队和未知车型统一返回 `422`。

## 计算口径

直接运营排放：

```text
E = sum(n_i * d_i * EF_i * LF_i) / 1000
```

- `n_i`：车型数量
- `d_i`：年均运营里程
- `EF_i`：车辆直接排放因子
- `LF_i`：低满载率调整系数

模拟碳预算差额（默认减排目标 `r_target=10%`，页面可调整）：

```text
Gap = E - B
B = sum(n_i * EF_i * d_reference_i * (1 - r_target)) / 1000
```

`B` 由排放因子、参考年均里程和用户选择的情景减排目标直接计算，可复算并用于敏感性分析；内部计算保留原始精度，仅在最终响应和展示时四舍五入。它不是官方分配的免费配额或政策目标。情景金额使用全国碳市场历史价格作对标，不能解释为物流企业当前履约成本或确定收益。CSV 中标为全生命周期或区域电网情景的电动车因子不会进入直接运营车型列表。

## 验证

```powershell
python -m pytest -q
python scripts\e2e_demo.py
python scripts\test_rag_pipeline.py
python scripts\verify_real_fleets.py
```

RAG 验收包含两项硬性相关性断言：

- “物流运输工具碳排放怎么核算”首条命中运输工具核算方法
- “交通运输行业碳达峰目标”首条命中交通运输碳达峰实施方案

PDF 测试会检查预算字段、科研免责声明、新能源核算边界、页码和字体兼容单位。

CI 已在远端运行：`.github/workflows/ci.yml`（工作流 `Tests`）在每次 push 到 `main` 时
执行 ruff、政策入库、全量测试与 RAG 基准回归，运行记录见
`https://github.com/zhutmg00-eng/big_0910/actions`。`docs/ci-workflow-template.yml`
是早期保留的简化模板，**不代表 CI 未启用**——判断依据只有远端运行记录。

## 实证验证进展（2026-09 更新）

### 已完成

- 构建 4 组真实车队基准案例：顺丰控股、中通快递、京东物流（2023 年 ESG/可持续发展报告披露）与 G7易流《公路货运碳账本》/智慧货运中心实测冷链车队，覆盖干支综合、长途甩挂、绿色仓配、冷链城配 4 类业务场景，合计 51,990 辆（其中燃油车 31,970 辆、新能源车 20,020 辆），来源全部可公开复核。
  - 数据与出处：`data/raw/real_fleets/`（benchmark_fleets.csv/json + sources_and_methodology.md）
- 活动水平估算法 vs 企业能源台账法对照验证：`scripts/verify_real_fleets.py`，4 家大型车队标定点误差（等权 MAPE）4.23%，单样本 +3.84%/+1.66%/+4.17%/+7.27%；敏感性网格（50 组输入偏差）误差中位 14.51%、最坏 29.80%。去掉 LF 保守偏置后标定点误差为 3.54%。这是“标定点 + 误差包络 + 适用边界”，不是通用准确率。
  - 报告：`docs/real_fleet_validation_report.md`（含误差根因分析）
  - 敏感性：`docs/sensitivity_report.md` 与 `scripts/sensitivity_analysis.py`（满载率/里程扰动下误差方向恒为正偏，量化了满载率假设这一主要误差来源）
  - 自动化测试：`tests/test_real_fleet_benchmarks.py`

### 已完成的核心科研实验能力

1. **实证车队基准检验（支撑 RQ1/RQ3）**：
   - 4 组公开车队数据集（顺丰、中通、京东、区域冷链实测，合计 51,990 辆）与核算方法学。
   - 自动化对比活动水平估算法与能源台账法：标定点误差：案例等权 MAPE 4.23%、按排放量加权 2.38%（n=4，误差包络见 docs/sensitivity_report.md）
     （`docs/real_fleet_validation_report.md`、`docs/derived_metrics.json`）。
   - 活动参数与披露能耗的一致性核验（等效燃料量比值 + 反推百公里油耗，
     `scripts/check_fleet_ledger_consistency.py`）。
   - 实载率与里程二维网格敏感性分析（`scripts/sensitivity_analysis.py`、`docs/sensitivity_report.md`）。
2. **政策问答评测与检索对照实验（支撑 RQ2）**：
   - 自建 40 题双碳法规与绿色交通基准题库（含金标答案、官方文件溯源与负例拒答设计）。
   - 双人背靠背独立审校与一致性报告（`docs/rag_benchmark/review/`）。**这条证据要谨慎引用**：
     两位标注者在两个编码字段上取值零变异（全 `✓`、全 `同意`），Cohen's Kappa 恒等于 1 属于数学退化，
     不能证明独立评审者会给出相同判断；`scripts/check_annotation_agreement.py` 可复算。
     该栏只能证明"最终稿两人无争议"，不构成严谨性证据。
   - 金标 chunk 在 v0.4 快照（37 份文档 / 268 块）上定块，固化于 `docs/rag_benchmark/rag_benchmark_gold_dataset.json`；
     v0.4.1 知识库扩至 39 份 / 281 块后完整重跑，v0.4 快照结果保存在 `archive_kb37_268_results.json`，
     两份结果文件都记录 `kb_fingerprint` 与 `rrf_weights`，语料或权重一变指标就不可比。
   - 6 组检索方案对照 + 配对 Wilcoxon 检验（Holm 校正）+ Bootstrap 95% CI。
     RQ2 正式结果保留在 39 份 / 281 块冻结快照上：三路 RRF MRR 0.492 [0.367, 0.618]、
     Recall@10 80.0%；纯向量 Recall@10 57.5%；英文默认嵌入纯向量 Recall@10 15%（消融）。
     2026-10-25 加入《绿色交通发展"十五五"规划》官方解读后，知识库为 40 份 / 287 块，
     同题复测 MRR 0.478 [0.352, 0.611]、Recall@10 80.0%——金标未重标，正式口径仍是冻结快照，
     复测对照见实验报告附录 C。
     Recall@k 的分母是全部 40 题，包含 4 道负例题——负例题考察的是"能否召回到支撑拒答的条款"，
     不是"能否命中金标 chunk"，两者混在同一个分母里，所以 Recall@10 的绝对值不可与只算正例的论文直接对比；
     负例题单独看负例依据召回率（4 题主集内默认方案 50%，见实验报告表最后一列）。
   - **反事实负例另有 30 题扩充集**（`negative_benchmark_30_questions.json`）：
     它是主集 4 道负例的**超集扩充**，不是独立第三套数据。单独评测下默认三路 RRF
     的负例依据召回率 Recall@5 为 30.0%，且在负例集上按 MRR 并非最优（最优为字面启发式 0.278）
     ——该不一致如实记录在实验报告三·二节，未据此调参（同集调参属循环论证）。
   - **字面启发式（MRR 0.488）与三路 RRF（0.492）几乎持平，为什么还默认用三路 RRF**：
     三者的 MRR 差距经 Holm 校正后都不显著，所以默认方案的取舍依据不是"MRR 更高"，
     而是 ①Recall@10 三路 RRF 达到 80.0%，比字面启发式的 70.0% 高 10 个百分点，召回不足时后面
     生成环节再准也没用；②字面启发式里的主题加权规则是照着这批题写的，存在对评测集过拟合的风险，
     三路 RRF 把它降为一路信号（权重 0.8）而不是唯一打分依据。这个取舍是设计判断，不是统计结论。
     三路融合权重为 BM25 0.6 : 向量 0.1 : 字面规则 0.8——等权融合的 MRR 只有 0.411，低于它要取代的
     v0.3 方案，权重稳健性用 5 折交叉验证单独检查
     （`docs/rag_benchmark/rrf_weight_cross_validation.md`）。详见 `docs/rag_benchmark/rag_retrieval_experiment_report.md`。
3. **Scope 2 外购电间接排放与运输周转量核算**：
   - 依据生态环境部、国家统计局《关于发布 2023 年电力二氧化碳排放因子的公告》（2025 年第 47 号）
     收录全国、区域（7 个）与省级（30 个）电网排放因子。
   - 构建纯电物流车耗电率模型，量化油电替代的净减排贡献，并给出临界电网碳强度判据
     （重卡 0.5847、轻卡 1.0686 kgCO₂/kWh）。
   - 支持货物周转量（万吨公里）核算及营运运输碳排放强度（gCO₂/(t·km)）对标
     （`src/engine/indirect_emission.py`）。
4. **专家咨询评审**（未完成，答辩前需补齐）：
   - 量化量表已定稿，涵盖科学性、检索保真度、落地性与免责审慎度四个维度
     （`docs/expert_review/评审指标规范与量化评分量表.md`；该目录为私有材料，不入 Git）。
   - 曾按该量表做过一次课题组内部的试评，用于打磨量表本身。这次试评**不是外部专家评审**，
     因此不在 README 中给出任何分数——没有签名、没有单位、没有原件的评分不能作为成果证据。
   - 待办：邀请两位外部专家（高校交通能源方向教师、物流企业 ESG 负责人）背靠背独立评审，
     收回有签名与单位的书面意见，答辩时提交原件；在此之前本项目不主张任何"专家评分"。

### 自动化测试与 CI 流水线

**测试基线**（在项目 venv 上实测，命令可复现；数字以实际运行为准）：

| 范围 | 命令 | 结果 |
|---|---|---|
| `tests/` 目录 | `python -m pytest tests -q` | 全部通过 |
| 全仓（含 `scripts/` 内的集成测试） | `python -m pytest -q` | 全部通过、0 失败 |

> 上方表格**故意不写用例数**。之前的版本在这里写死了 247 / 248，而真实收集数早已是
> 他们的 1.6 倍——同一段下面还写着「不要手工维护测试数」，等于自己违反了自己的规定。
> 不要在文档里手工维护「测试数」作为卖点：该数字随每次提交变化，历史上出现过
> 105 / 106 / 107 / 117 / 119 / 159 / 170 / 173 / 220 / 221 / 239 / 241 / 247 / 248
> 十余种互相冲突的写法。需要引用时执行 `python -m pytest --collect-only -q` 读最后一行。
> `tests/test_claim_consistency.py::test_defense_docs_test_count_matches_collection`
> 会自己向 pytest 要真实收集数再与答辩材料逐字比对，两边都不写死。

知识库为空时 2 项 RAG 基准测试会 skip 而非失败，所以必须先在本地跑
`python scripts/ingest_policy_docs.py --force` 再数测试；CI 里设置 `RAG_BENCH_REQUIRED=1`，知识库缺失就直接失败。

- GitHub Actions 流水线（`.github/workflows/ci.yml`）：集成系统字体、依赖安装、政策定块入库及全量测试自动执行。
  流水线用 Python 3.11，本地上表基线是 3.10.20，两者不是同一解释器——CI 绿不等于本地绿，反之亦然。

## 许可

本项目为大学生创新创业训练计划科研原型，仅供教学和研究使用。
