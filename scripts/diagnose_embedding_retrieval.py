#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""嵌入检索诊断：量化当前嵌入模型在中文法规切片上的区分度，判断"检索失败"是
嵌入模型的表征能力问题，还是检索管线的实现问题。

为什么需要这个脚本
------------------
`evaluate_rag_benchmark.py` 给出的组 B（纯向量）指标很吓人：Recall@3 只有 2.5%、
MRR 0.0411。下结论之前必须排除"管线有 bug"这一可能：如果检索实现本身有问题
（例如查询向量与库向量不在同一空间），那么低指标反映的是代码缺陷，而不是嵌入模型的问题。

本脚本用最直接的方式做这个排除：直接对全部 268 个切片做一次全量余弦检索，
统计 gold 切片的名次分布与分数间隔。不做任何重排、不加任何规则。

关键判据
--------
- 若 gold 切片的名次分布是**连续、可解释**的（多数落在中段而非全部垫底），
  且分数间隔（gold 与最高分切片的距离差）呈连续分布 → 说明管线正常，
  低指标源自嵌入表征能力；
- 若 gold 切片几乎全部落在末位、或分数间隔恒为 0 → 说明管线或向量空间有问题，
  此时不得把低指标归因于"语义弥散"。

用法（仓库根目录）：
    python scripts/diagnose_embedding_retrieval.py
    python scripts/diagnose_embedding_retrieval.py --json
"""
import json
import statistics
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.rag.vector_store import PolicyVectorStore  # noqa: E402

GOLD = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.json"
OUT = PROJECT_ROOT / "docs" / "embedding_diagnostic.json"


def main() -> dict:
    vs = PolicyVectorStore()
    stats = vs.get_stats()
    dataset = json.loads(GOLD.read_text(encoding="utf-8"))
    total_chunks = int(stats.get("total_chunks", vs.collection.count()))

    per_question = []
    for item in dataset:
        gold = set(item["gold_chunk_ids"])
        res = vs.collection.query(query_texts=[item["question"]], n_results=total_chunks)
        order = res["ids"][0]
        dists = res["distances"][0]
        rank = next((i + 1 for i, cid in enumerate(order) if cid in gold), 0)
        top_dist = dists[0]
        gold_dist = dists[rank - 1] if rank else None
        per_question.append({
            "id": item["id"],
            "theme": item["theme"],
            "type": item.get("type"),
            "applicability_label": item.get("applicability_label"),
            "gold_rank": rank,
            "gold_distance": round(gold_dist, 4) if gold_dist is not None else None,
            "top1_distance": round(top_dist, 4),
            "distance_gap": round(gold_dist - top_dist, 4) if gold_dist is not None else None,
            "recall_at_3": bool(rank and rank <= 3),
            "recall_at_10": bool(rank and rank <= 10),
        })

    ranks = [q["gold_rank"] for q in per_question if q["gold_rank"]]
    gaps = [q["distance_gap"] for q in per_question if q["distance_gap"] is not None]
    n = len(per_question)

    summary = {
        "n_questions": n,
        "total_chunks": total_chunks,
        "embedding_model": stats.get("embedding_model"),
        "vector_store_mode": stats.get("mode"),
        "recall_at_3": round(sum(1 for q in per_question if q["recall_at_3"]) / n, 4),
        "recall_at_10": round(sum(1 for q in per_question if q["recall_at_10"]) / n, 4),
        "mrr": round(sum(1 / q["gold_rank"] for q in per_question if q["gold_rank"]) / n, 4),
        "gold_rank_median": statistics.median(ranks) if ranks else None,
        "gold_rank_min": min(ranks) if ranks else None,
        "gold_rank_max": max(ranks) if ranks else None,
        "never_retrieved": sum(1 for q in per_question if not q["gold_rank"]),
        "distance_gap_median": round(statistics.median(gaps), 4) if gaps else None,
        "distance_gap_min": round(min(gaps), 4) if gaps else None,
        "distance_gap_max": round(max(gaps), 4) if gaps else None,
    }
    return {"summary": summary, "per_question": per_question}


def report(res: dict) -> None:
    s = res["summary"]
    print("=" * 84)
    print(" 嵌入检索诊断：gold 切片在全量切片中的名次分布")
    print("=" * 84)
    print(f"嵌入模型（配置值）      : {s['embedding_model']}")
    print(f"向量库模式              : {s['vector_store_mode']}")
    print(f"切片总数 / 题目数       : {s['total_chunks']} / {s['n_questions']}")
    print(f"Recall@3 / Recall@10    : {s['recall_at_3']:.1%} / {s['recall_at_10']:.1%}")
    print(f"MRR（全量检索口径）      : {s['mrr']:.4f}")
    print(f"gold 名次 中位/最小/最大 : {s['gold_rank_median']} / {s['gold_rank_min']} / {s['gold_rank_max']}")
    print(f"完全未召回题数          : {s['never_retrieved']}")
    print(f"gold 与最高分切片的距离差 中位/最小/最大: {s['distance_gap_median']} / "
          f"{s['distance_gap_min']} / {s['distance_gap_max']}")
    print("-" * 84)
    print("读法：")
    print("1. 若 gold 名次分布连续（多数落在中段而不是全部垫底），且距离差呈连续分布，")
    print("   说明检索管线本身正常，低指标来自嵌入模型的表征能力，而不是代码缺陷；")
    print("2. 若 gold 几乎全部垫底、或距离差恒为 0，则说明向量空间或管线有问题，")
    print("   此时不得把低指标解释为'中文法规语义弥散'；")
    print("3. 该诊断只做测量，不修改任何参数，也不用于反向调参。")
    print("=" * 84)
    # 名次分布直方
    buckets = [(1, 3), (4, 10), (11, 30), (31, 60), (61, 120), (121, 268)]
    print("名次分布：")
    for lo, hi in buckets:
        c = sum(1 for q in res["per_question"] if q["gold_rank"] and lo <= q["gold_rank"] <= hi)
        print(f"  {lo:>4}-{hi:<4} : {c:>3} 题  {'#' * c}")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    result = main()
    if "--json" in sys.argv:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        report(result)
        OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n机器可读结果: {OUT}")
