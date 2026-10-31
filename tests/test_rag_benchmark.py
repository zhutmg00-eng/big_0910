"""RAG 政策问答基准评测持续集成与回归测试"""
import json
import os

import pytest
from pathlib import Path
from src.rag.vector_store import PolicyVectorStore
from scripts.evaluate_rag_benchmark import calculate_mrr, wilcoxon_signed_rank

PROJECT_ROOT = Path(__file__).parent.parent
GOLD_DATASET_PATH = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.json"

def _kb_ids_or_skip(vs) -> set:
    """知识库为空时：本地跳过；CI（RAG_BENCH_REQUIRED=1）直接失败，防止回归测试被静默跳过。"""
    if vs.count() == 0 or not vs.get_stats()["mode"] == "chromadb":
        msg = "向量知识库未初始化或处于降级模式，请先运行 python scripts/ingest_policy_docs.py"
        if os.getenv("RAG_BENCH_REQUIRED") == "1":
            pytest.fail(msg)
        pytest.skip(msg)
    return set(vs._corpus()["ids"])


def test_gold_dataset_integrity():
    """验证基准数据集 40 题完整性与 gold_chunk_ids 有效性"""
    assert GOLD_DATASET_PATH.exists(), f"未找到金标评测集: {GOLD_DATASET_PATH}"
    dataset = json.loads(GOLD_DATASET_PATH.read_text(encoding="utf-8"))
    assert len(dataset) == 40, f"评测题目数应为40，实际为: {len(dataset)}"

    vs = PolicyVectorStore()
    existing_chunk_ids = _kb_ids_or_skip(vs)
    assert len(existing_chunk_ids) >= 268, f"政策库 chunk 数不足: {len(existing_chunk_ids)}"

    for item in dataset:
        assert item["id"].startswith("Q"), f"题号格式错误: {item['id']}"
        assert item["question"], f"{item['id']} 题目为空"
        assert item["gold_chunk_ids"], f"{item['id']} 缺少金标 chunk_id"
        # 确保所有 gold chunk id 均真实存在于知识库中
        for cid in item["gold_chunk_ids"]:
            assert cid in existing_chunk_ids, f"{item['id']} 的金标 chunk {cid} 在知识库中不存在"

def test_hybrid_retrieval_benchmark_performance():
    """验证生产检索路径（三路 RRF，RETRIEVAL_MODE 默认值）在基准集上的核心性能门槛 (MRR >= 0.45, Recall@10 >= 0.70)。

    2026-10-31 对齐说明：本测试原先调用遗留的 mode="hybrid"（v0.3 两路融合，非生产路径），
    其在 38 份/284 块当前库上 MRR 仅 0.4372（旧错误语料下也只有 0.4586，红线余量 0.009）；
    生产默认 rrf3 同库实测 0.457。守卫应看住用户实际得到的检索路径，故改为 mode="rrf3"。
    依据：docs/rag_benchmark/rag_retrieval_experiment_report.md 附录 C 与 known_gaps GAP-6。
    """
    dataset = json.loads(GOLD_DATASET_PATH.read_text(encoding="utf-8"))
    vs = PolicyVectorStore()
    _kb_ids_or_skip(vs)

    ranks = []
    hits10 = 0
    for item in dataset:
        query = item["question"]
        gids = set(item["gold_chunk_ids"])
        retrieved = vs.search(query, k=10, mode="rrf3")
        r_ids = [r["id"] for r in retrieved]

        first_rank = 0
        for idx, cid in enumerate(r_ids, 1):
            if cid in gids:
                first_rank = idx
                break
        ranks.append(first_rank)
        if first_rank > 0:
            hits10 += 1

    mrr = calculate_mrr(ranks)
    recall_10 = hits10 / len(dataset)

    assert mrr >= 0.45, f"混合检索 MRR 低于质量红线 0.45: {mrr:.4f}"
    assert recall_10 >= 0.70, f"混合检索 Recall@10 低于质量红线 0.70: {recall_10:.2%}"

def test_wilcoxon_statistical_test_logic():
    """验证 Wilcoxon 符号秩检验算法逻辑有效性"""
    x = [1.0, 0.5, 0.33, 1.0, 0.5, 1.0, 0.5, 0.33]
    y = [0.0, 0.1, 0.0, 0.2, 0.1, 0.0, 0.1, 0.0]
    w, p = wilcoxon_signed_rank(x, y)
    assert p < 0.05, f"预期差异显著，但 p={p}"
