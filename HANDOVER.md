# 项目交接说明

最后更新：2026-08-26

当前阶段：Phase 3 原型集成完成，进入 Phase 4/5 实证验证准备

代码分支：`main`

## 一、当前定位

项目当前名称为“物流碳排放与减排情景决策助手”。它是大创科研原型，不是碳市场履约系统。

必须保持以下口径：

- 物流运输行业目前未纳入全国碳市场配额管理。
- `quota.py` 中的基准按“排放因子 × 参考里程 × (1-情景减排目标)”生成，默认目标为10%；内部旧命名仅为兼容现有代码保留。
- 预算差额不代表法定配额缺口、履约义务或可交易资产。
- 碳价换算只表示情景成本或潜在价值，不表示实际成本或收益。
- 新能源物流车当前只按直接运营排放为零计算，未计购电间接排放和全生命周期排放。

后续开发不得把上述内容改回“需购买配额”或“盈余可出售”。

## 二、已完成能力

### 计算与情景

- 车队直接运营排放基线
- 低满载率调整
- 模拟碳预算差额
- 可配置模拟预算减排目标，所有可选直接运营车型均使用同一可复算公式
- 碳价对标情景金额
- 新能源替代、满载率提升、多情景比较和方案排序
- 多企业 API 对比

### RAG

- PDF、DOCX、HTML、Markdown、TXT 解析
- ICP、版权、网站标识、导航等网页噪声清洗
- 重复长行去重和文档切分
- ChromaDB 语义召回 + 中文标题/关键词混合重排
- `EMBEDDING_MODEL` 实际控制嵌入函数
- 无 LLM 密钥时返回带来源的原文摘录
- Prompt 明确要求先判断政策适用范围

### 前端、报告和部署

- Streamlit 6 个导航页面
- API 地址、API Key、超时和错误详情可配置
- PDF 使用正确的模拟预算字段、`tCO2e` 单位、科研免责声明和页码
- Dockerfile 默认启动 API
- Compose 分别启动 API 和 Web，健康检查使用 Python 标准库
- 生产 Compose 要求显式密钥和 CORS，XSRF 防护开启

### 质量保障

- 请求模型拒绝空企业名、空车队、负车辆数、负里程、越界满载率和未知车型
- 全生命周期及区域电网电动车因子只保留为CSV研究资料，不混入直接运营车型
- 自动化测试数随每次提交变化，不在文档里写死；需要时执行
  `python -m pytest --collect-only -q` 读最后一行，或用
  `python scripts/sync_deck_test_count.py --check` 核对载体是否已同步
- RAG 脚本对两条代表性查询执行首条命中断言
- PDF 测试检查内容和页码
- CI 在远端运行（`.github/workflows/ci.yml`，工作流 `Tests`，Python 3.11）：
  ruff → 政策入库 → 全量测试（含覆盖率）→ RAG 基准回归，运行记录见
  `https://github.com/zhutmg00-eng/big_0910/actions`。仓库内只有这一份 workflow，
  早期那份 `docs/ci-workflow-template.yml` 已删除（内容已分叉且误导）

## 三、运行方式

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m pytest -q
```

```powershell
# 终端 1
uvicorn src.api.main:app --reload --port 8000

# 终端 2
streamlit run src/ui/app.py
```

Docker：

```powershell
docker compose up --build
```

## 四、验收入口

```powershell
python -m pytest -q
python scripts\e2e_demo.py
python scripts\test_rag_pipeline.py
```

浏览器需验证：

1. 碳排放盘点可添加车队并成功计算。
2. 页面显示模拟预算差额和科研口径，不出现法定配额承诺。
3. 政策顾问在无 LLM 密钥时仍返回带来源的检索式回答。
4. 报告页导出的 PDF 显示正确预算、页码和方法边界。

## 五、数据说明

- `data/raw/real_fleets/`：真实公开车队基准数据集（顺丰、中通、京东、冷链实测）及核算方法学。
- `data/raw/emission_factors.csv`：排放因子与扩展车型数据。
- `data/raw/carbon_price_history.csv`：碳价研究数据，其中包含插值记录，只能用于情景演示。
- `data/policy_docs/`：政策 Markdown 文档及少量下载日志。
- `data/chroma_db/`：运行时索引，已由 `.gitignore` 排除。
- `data/reports/`：示例和运行时报告；不要覆盖用户自行生成的未跟踪文件。

任何对外材料必须区分真实观测、插值、原型参数和官方政策原文。

### 实证验证能力
- `scripts/verify_real_fleets.py`：自动对比活动水平估算法与能源消耗台账法，输出相对误差矩阵（全样本 MAPE 4.23%）。
- `tests/test_real_fleet_benchmarks.py`：5项自动化测试用例，全量测试已增至 66 项。
- `docs/real_fleet_validation_report.md`：完整的实证验证与误差根因分析报告。

## 六、大创适配性判断

项目适合作为大创，但必须以“研究问题 + 实验 + 原型”组织成果。单纯展示 Streamlit、RAG 和 PDF 不足以形成有说服力的创新训练结题。

推荐研究问题：

1. 在数据有限条件下，车队运营参数能否形成可解释的物流直接排放估算？误差来源是什么？
2. 标题与关键词混合重排能否提升交通低碳政策检索的相关性和适用范围判断？
3. 不同车队更新与运营优化情景对直接排放和不确定性区间有何影响？

最低实证要求：

- 至少 1 组匿名真实车队或可复核公开样本；
- 30 至 50 道政策问题及标准来源标签；
- 纯关键词、纯向量、混合检索三组对照；
- Recall@k、MRR、引用准确率、适用范围准确率和人工评分；
- 排放因子、里程、满载率的敏感性或不确定性分析；
- 专业教师或企业人员的盲评记录。

## 七、下一步优先级

1. 真实样本和评价集，优先级最高。
2. 购电间接排放与运输周转量口径。
3. RAG 对照实验、误差案例和适用范围分类。
4. 中期汇报中的研究问题、证据链和局限性表达。
5. 在上述工作完成后再考虑 UI 美化或增加功能。

## 八、历史文件

`PHASE3_*.md` 是阶段性记录，部分旧术语已被本文件和 README 中的新口径取代。出现冲突时，以当前代码、README 和本交接说明为准。
