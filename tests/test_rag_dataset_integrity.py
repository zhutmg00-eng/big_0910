"""评测集自身的完整性：金标块必须真的来自题目登记的来源文件。

背景（真实缺陷，实测于 2026-10-27）：
`scripts/map_gold_chunks.py` 从审校表的 `gold_anchor` 里解析出**多个**文件
（例如「A.md-第二十九条；B.md-五、（二）」），把这些文件的 chunk 一并写进
`gold_chunk_ids`；但 `source_files` 只照抄题库 Markdown 的来源栏，于是出现
「gold 块来自 B.md，source_files 却没有 B.md」的题。

`scripts/evaluate_rag_benchmark.py` 的 `Source_Hit@k` 逐题判断
`any(s in sources[:k] for s in source_files)`——来源清单缺文件时，检索哪怕把
B.md 排在第一也不算命中，指标被系统性低估。40 题集里 8 题如此，30 题负例集 2 题。

本文件锁两件事：
1. 两份评测集里每道题的 `gold_chunk_ids` 都能在**当前知识库**里找到；
2. 每个 gold 块的真实来源文件都出现在该题的 `source_files` 里。

知识库为空时跳过第 1、2 项（全新 clone 尚未 ingest），避免把「没建库」误报成
「数据坏了」；但只要库在，就必须一致。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
DATASETS = (
    "docs/rag_benchmark/rag_benchmark_gold_dataset.json",
    "docs/rag_benchmark/negative_benchmark_30_questions.json",
)


def _load(rel: str) -> list[dict]:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def _corpus() -> dict:
    """当前知识库的 id → (text, metadata)。空库返回 {} 以便上层 skip。"""
    import sys

    sys.path.insert(0, str(ROOT))
    from src.rag.vector_store import PolicyVectorStore

    store = PolicyVectorStore()
    if store.count() == 0:
        return {}
    return store._corpus()["by_id"]


@pytest.fixture(scope="module")
def corpus() -> dict:
    got = _corpus()
    if not got:
        pytest.skip("知识库为空（未运行 ingest），跳过金标块存在性校验")
    return got


@pytest.mark.parametrize("rel", DATASETS)
def test_gold_chunks_exist_in_current_kb(rel: str, corpus: dict) -> None:
    """金标 chunk_id 必须能在当前知识库里解析到，否则整题指标恒为 0。"""
    missing = []
    for q in _load(rel):
        for cid in q.get("gold_chunk_ids", []):
            if cid not in corpus:
                missing.append((q["id"], cid))
    assert not missing, (
        f"{rel} 有 {len(missing)} 个 gold_chunk_id 不在当前知识库中（前 5 条：{missing[:5]}）。"
        "换语料或改分块参数后必须重新映射金标。"
    )


@pytest.mark.parametrize("rel", DATASETS)
def test_source_files_cover_gold_chunk_origins(rel: str, corpus: dict) -> None:
    """gold 块的真实来源文件必须写进 source_files，否则 Source_Hit@k 漏算。"""
    problems = []
    for q in _load(rel):
        declared = set(q.get("source_files") or [])
        actual = {
            corpus[cid][1].get("source", "")
            for cid in q.get("gold_chunk_ids", [])
            if cid in corpus
        }
        undeclared = sorted(actual - declared - {""})
        if undeclared:
            problems.append((q["id"], undeclared))
    assert not problems, (
        f"{rel} 有 {len(problems)} 题的 source_files 未覆盖 gold 块来源：{problems[:5]}。"
        "Source_Hit@k 会因此统计偏低（详见本文件头部说明）。"
    )


def test_gold_dataset_has_unique_ids() -> None:
    """题号重复会让 summarize 的分母失真。"""
    for rel in DATASETS:
        ids = [q["id"] for q in _load(rel)]
        dupes = sorted({i for i in ids if ids.count(i) > 1})
        assert not dupes, f"{rel} 存在重复题号：{dupes}"


def test_every_question_has_at_least_one_gold_chunk() -> None:
    """没有 gold 块的题在 MRR / Recall 里恒记 0 分，属于数据缺失而非检索失败。"""
    for rel in DATASETS:
        empty = [q["id"] for q in _load(rel) if not q.get("gold_chunk_ids")]
        assert not empty, f"{rel} 有 {len(empty)} 题缺少 gold_chunk_ids：{empty[:5]}"
