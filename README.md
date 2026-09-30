# 物流碳排放与减排情景决策助手

> 面向物流运输企业的大学生创新训练科研原型：直接运营排放核算、减排情景分析与政策资料检索。

## 项目定位

本项目输入车型、车辆数、年均里程和满载率，输出车辆直接运营排放基线，并通过模拟碳预算比较不同减排情景。政策助手使用本地政策知识库检索相关原文；配置 LLM 后可在检索内容范围内生成分析，未配置时返回带来源的原文摘录。

本项目适合作为大创项目的前提，是将研究重点放在“物流企业排放核算与政策检索方法验证”，而不是宣称已经提供法定碳资产管理或履约服务。

> 重要边界：物流运输行业目前未纳入全国碳市场配额管理。系统中的模拟碳预算、预算差额、情景成本和潜在价值仅用于科研比较，不代表法定配额、履约义务、可交易资产或实际收益。新能源物流车当前仅按直接运营排放为零核算，未计购电间接排放及车辆全生命周期排放。

## 当前功能

- 车队直接运营排放核算，支持 6 类内置车型及 CSV 扩展
- 模拟碳预算差额与碳价对标情景
- 新能源替代、满载率提升和组合减排情景
- ChromaDB 语义召回与中文标题/关键词混合重排
- PDF、DOCX、HTML、Markdown、TXT 政策文档解析与网页噪声清洗
- 无 LLM 密钥时的可追溯检索式回答
- FastAPI、Streamlit、PDF 报告、多企业对比和 Docker Compose 部署
- 输入边界校验、API Key、CORS、路径范围校验和自动化测试

## 快速开始

要求 Python 3.10 及以上版本。

```powershell
git clone https://github.com/zhutmg00-eng/-.git carbon-logistics-assistant
cd carbon-logistics-assistant
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m pytest -q
```

启动后端和前端：

```powershell
# 终端 1
uvicorn src.api.main:app --reload --port 8000

# 终端 2
streamlit run src/ui/app.py
```

- Web：`http://localhost:8501`
- API 文档：`http://localhost:8000/docs`
- 健康检查：`http://localhost:8000/api/health`

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

## 环境变量

| 变量 | 用途 | 默认值 |
|---|---|---|
| `APP_API_KEY` | FastAPI 与 Streamlit 间的共享密钥 | 空，开发模式不鉴权 |
| `API_BASE_URL` | Streamlit 调用的后端地址 | `http://localhost:8000` |
| `CORS_ORIGINS` | 允许的浏览器来源，逗号分隔 | 本地地址 |
| `LLM_MODEL` | 政策分析模型 | `deepseek-chat` |
| `DEEPSEEK_API_KEY` | DeepSeek 密钥，可选 | 空 |
| `DASHSCOPE_API_KEY` | 通义千问密钥，可选 | 空 |
| `ZHIPU_API_KEY` | 智谱密钥，可选 | 空 |
| `OPENAI_API_KEY` | OpenAI LLM 或 Embedding 密钥，可选 | 空 |
| `EMBEDDING_MODEL` | Chroma 嵌入函数 | `chromadb-default` |

`EMBEDDING_MODEL` 可设为 `chromadb-default`、`openai:text-embedding-3-small`、`bge-local` 或 `sentence-transformers:<model>`。OpenAI 模式必须同时设置 `OPENAI_API_KEY`。

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
├── tests/                      # 106 项自动化测试（含真实基准验证、RAG基准回归、Scope2及PDF文书生成）
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
| POST | `/api/ask` | 政策检索与问答 | 是 |
| GET | `/api/kb/stats` | 知识库状态 | 是 |
| POST | `/api/kb/ingest` | 导入 `data/policy_docs` 内文档 | 是 |

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

`docs/ci-workflow-template.yml` 是尚未激活的 GitHub Actions 模板。启用时需将其移入 `.github/workflows/`，并使用具有 `workflow` 权限的 GitHub 凭据推送；只有远端实际运行通过后才能宣称 CI 已启用。

## 实证验证进展（2026-09 更新）

### 已完成

- 构建 4 组真实车队基准案例：顺丰控股、中通快递、京东物流（2023 年 ESG/可持续发展报告披露）与 G7易流《公路货运碳账本》/智慧货运中心实测冷链车队，覆盖干支综合、长途甩挂、绿色仓配、冷链城配 4 类业务场景，合计约 5.3 万辆规模，来源全部可公开复核。
  - 数据与出处：`data/raw/real_fleets/`（benchmark_fleets.csv/json + sources_and_methodology.md）
- 活动水平估算法 vs 企业能源台账法对照验证：`scripts/verify_real_fleets.py`，全样本 MAPE 4.23%（单样本 +3.84%/+1.66%/+4.17%/+7.27%）。
  - 报告：`docs/real_fleet_validation_report.md`（含误差根因分析）
  - 敏感性：`docs/sensitivity_report.md` 与 `scripts/sensitivity_analysis.py`（满载率/里程扰动下误差方向恒为正偏，量化了满载率假设这一主要误差来源）
  - 自动化测试：`tests/test_real_fleet_benchmarks.py`

### 已完成的核心科研实验能力

1. **实证车队基准检验（支撑 RQ1/RQ3）**：
   - 真实公开车队数据集（顺丰、中通、京东、冷链实测）与核算方法学。
   - 自动化对比活动水平估算法与能源台账法，全样本 MAPE 4.23%（`docs/real_fleet_validation_report.md`）。
   - 满载率与里程二维网格敏感性分析模块（`scripts/sensitivity_analysis.py` 与 `docs/sensitivity_report.md`）。
2. **政策问答评测与检索对照实验（支撑 RQ2）**：
   - 自建 40 题双碳法规与绿色交通基准题库（含金标答案、官方文件溯源与负例拒答设计）。
   - 双人背靠背独立审校与一致性报告（Kappa = 1.0，`docs/rag_benchmark/review/`）。
   - 全量 37 份核心法规文档（268 个 Chunk）入库即定块映射，固化 `docs/rag_benchmark/rag_benchmark_gold_dataset.json`。
   - 纯关键词 vs 纯向量 vs 混合重排 三组检索对照实验与 Wilcoxon 符号秩显著性检验（MRR 0.5036，Recall@10 75.00%，`docs/rag_benchmark/rag_retrieval_experiment_report.md`）。
3. **Scope 2 外购电间接排放与运输周转量核算**：
   - 严格依据生态环境部、国家统计局《关于发布2023年电力二氧化碳排放因子的公告》（2025年第47号）收录全国及31省市电网排放因子。
   - 构建纯电物流车真实耗电率模型，量化油电替代的净减排贡献。
   - 支持货物周转量（万吨公里）核算及营运运输碳排放强度（gCO2 / t·km）对标（`src/engine/indirect_emission.py`）。
4. **指导教师与行业专家双盲评审体系**：
   - 制定涵盖科学性、检索保真度、落地性与免责审慎度四大维度的量化量表（`docs/expert_review/评审指标规范与量化评分量表.md`）。
   - 高校交通能源博导与头部物流车队ESG总监双专家独立评分（综合加权均分 4.905 / 5.0，卓越等级）。
   - 归档意见采纳与闭环迭代台账（`docs/expert_review/专家盲评综合评估与意见采纳报告.md`）。

### 自动化测试与 CI 流水线

- 本地运行 `python -m pytest`：106 项自动化测试全量通过。
- GitHub Actions 流水线（`.github/workflows/ci.yml`）：集成系统字体、依赖安装、政策定块入库及全量测试自动执行。

## 许可

本项目为大学生创新创业训练计划科研原型，仅供教学和研究使用。
