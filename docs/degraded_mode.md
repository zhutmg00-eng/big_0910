# 政策知识库降级运行说明（v0.4.1）

> 答辩演示**默认用完整模式**（中文向量 + BM25 + 字面规则三路 RRF）。降级模式只在出问题时兜底，不需要人为制造。

## 一、什么时候会自动降级

| 情况 | 系统行为 | `/api/kb/stats` |
|---|---|---|
| 未安装 chromadb | 整体使用 BM25 + JSON 持久化 | `mode: bm25_fallback`，`degrade_reason: chromadb 未安装` |
| chromadb 已装但初始化失败（库文件损坏、被锁、版本不兼容） | 同上，**不再抛异常** | `degrade_reason: ChromaDB 初始化失败：<异常类型>` |
| 嵌入模型缺失或下载失败 | 只跳过向量这一路，BM25 与字面规则照常融合 | `mode: chromadb`，`degrade_reason: 嵌入模型不可用：…` |
| 检索层出现其他任何异常 | `PolicyAdvisor` 返回空证据的兜底回答，`/api/ask` 不会 500 | — |

对应测试：`tests/test_graceful_degradation.py`（5 个用例）。

## 二、降级后的表现（答辩口径）

1. **检索**：只剩词法检索，措辞接近政策原文时效果好（如“配额清缴”“排放因子”“核算边界”），口语化提问命中率下降。演示时优先使用预设问题。
2. **回答生成**：与检索模式**无关**。配置了大模型 API Key 时仍然调用大模型，基于检索到的条款生成回答；没有配置 Key 时返回“检索结论 + 政策原文摘录”的抽取式回答。
3. **证据溯源**：`/api/ask` 响应中始终有结构化的 `retrieved_sources` 字段（来源文件、chunk_id、检索器、摘录、相关度），完整模式和降级模式都一样。

## 三、恢复完整模式

```bash
pip install -r requirements.txt            # 确认 chromadb、fastembed 已安装
rm -rf data/chroma_db                      # 库文件损坏时先删掉
python scripts/ingest_policy_docs.py --force
curl http://127.0.0.1:8000/api/kb/stats    # 应为 mode=chromadb，degrade_reason 为空
python -m pytest -q                        # RAG 基准测试在完整模式下才会运行，不应出现 skipped
```

## 四、知识库同步说明

- `python scripts/ingest_policy_docs.py` 按**文件内容哈希**增量同步：未修改的文档直接跳过，修改过的整体替换，从目录删除的文档会同步移出知识库。启动器每次启动都可以调用它，几秒内完成。
- 知识库增删文档后，**检索评测数字必须重新跑**（`python scripts/evaluate_rag_benchmark.py`）。评测结果里的 `kb_fingerprint` 记录了当时语料的指纹，PPT 和论文引用数字时请注明对应的知识库版本。
