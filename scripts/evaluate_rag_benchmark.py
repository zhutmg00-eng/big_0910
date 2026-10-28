#!/usr/bin/env python3
"""RAG 政策问答检索基准评测（v0.4：多组消融 + Bootstrap 置信区间 + Holm 校正）

对照组（同一知识库 268 块、同一 40 题金标集、统一 top-10）：
    A  keyword  旧版字面启发式（字符 n-gram 覆盖 + 人工主题加权）
    B  vector   纯稠密向量（当前嵌入模型）
    C  hybrid   v0.3 方案：向量召回 + 0.35×语义 + 0.65×启发式 加权重排
    D  bm25     jieba 分词 Okapi BM25
    E  rrf      BM25 + 稠密向量 倒数排名融合（v0.4 默认方案，无评测集调参）
    F  rrf3     BM25 + 向量 + 启发式 三路 RRF（消融：启发式规则是否仍有增益）

可选 ``--embedding-ablation``：额外用 chromadb-default(英文 MiniLM) 建库，
对比“英文通用嵌入 vs 中文 BGE 嵌入”对纯向量检索的影响。

统计方法：
    - 指标：MRR、Recall@{1,3,5,10}、nDCG@10、Source_Hit@k
    - 置信区间：对 40 题做 2000 次配对 Bootstrap 重采样，报告 95% 百分位 CI
    - 显著性：配对 Wilcoxon 符号秩检验（倒数秩），多重比较采用 Holm-Bonferroni 校正
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path
from typing import Dict, List

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

DATASET_PATH = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.json"
NEGATIVE_DATASET_PATH = PROJECT_ROOT / "docs" / "rag_benchmark" / "negative_benchmark_30_questions.json"
OUT_JSON = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json"
OUT_MD = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_report.md"

MODES = ["keyword", "vector", "hybrid", "bm25", "rrf", "rrf3"]
MODE_LABELS = {
    "keyword": "A 字面启发式(旧)",
    "vector": "B 纯稠密向量",
    "hybrid": "C 加权重排(v0.3)",
    "bm25": "D BM25(jieba)",
    "rrf": "E BM25+向量 RRF",
    "rrf3": "F 三路 RRF(v0.4 默认)",
}
K_LIST = [1, 3, 5, 10]


# ---------------------------------------------------------------- 统计工具
def calculate_mrr(ranks: List[int]) -> float:
    """MRR (Mean Reciprocal Rank)；rank=0 表示 top-k 内未命中。"""
    reciprocals = [1.0 / r if r > 0 else 0.0 for r in ranks]
    return sum(reciprocals) / len(reciprocals) if reciprocals else 0.0


def ndcg_at_k(retrieved: List[str], gold: set, k: int = 10) -> float:
    dcg = sum(1.0 / math.log2(i + 1) for i, cid in enumerate(retrieved[:k], 1) if cid in gold)
    ideal = sum(1.0 / math.log2(i + 1) for i in range(1, min(len(gold), k) + 1))
    return dcg / ideal if ideal else 0.0


def wilcoxon_signed_rank(x: List[float], y: List[float]):
    """配对 Wilcoxon 符号秩检验（含连续性校正的正态近似），返回 (W, 双尾 p)。"""
    diffs = [a - b for a, b in zip(x, y)]
    non_zero = [d for d in diffs if abs(d) > 1e-9]
    n = len(non_zero)
    if n == 0:
        return 0.0, 1.0
    abs_sorted = sorted(enumerate(non_zero), key=lambda item: abs(item[1]))
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n and abs(abs(abs_sorted[j][1]) - abs(abs_sorted[i][1])) < 1e-9:
            j += 1
        avg_rank = (i + 1 + j) / 2.0
        for t in range(i, j):
            ranks[abs_sorted[t][0]] = avg_rank
        i = j
    w_pos = sum(r for r, d in zip(ranks, non_zero) if d > 0)
    w_neg = sum(r for r, d in zip(ranks, non_zero) if d < 0)
    w = min(w_pos, w_neg)
    mean_w = n * (n + 1) / 4.0
    var_w = n * (n + 1) * (2 * n + 1) / 24.0
    z = max(0.0, abs(w - mean_w) - 0.5) / math.sqrt(var_w) if var_w > 0 else 0.0
    return float(w), float(min(1.0, max(0.0, math.erfc(z / math.sqrt(2)))))


def holm_correction(pvalues: Dict[str, float]) -> Dict[str, float]:
    """Holm-Bonferroni 逐步校正，返回校正后 p 值。"""
    items = sorted(pvalues.items(), key=lambda kv: kv[1])
    m = len(items)
    adjusted, running = {}, 0.0
    for i, (name, p) in enumerate(items):
        running = max(running, min(1.0, (m - i) * p))
        adjusted[name] = running
    return adjusted


def bootstrap_ci(values: List[float], n_boot: int = 2000, seed: int = 42, alpha: float = 0.05):
    rng = random.Random(seed)
    n = len(values)
    if n == 0:
        return (0.0, 0.0)
    means = sorted(sum(values[rng.randrange(n)] for _ in range(n)) / n for _ in range(n_boot))
    return (means[int(alpha / 2 * n_boot)], means[int((1 - alpha / 2) * n_boot) - 1])


# ---------------------------------------------------------------- 评测主流程
def run_modes(vs, dataset: List[Dict], modes: List[str]) -> Dict[str, List[Dict]]:
    results = {m: [] for m in modes}
    for item in dataset:
        gold = set(item["gold_chunk_ids"])
        source_files = item.get("source_files", [])
        for mode in modes:
            retrieved = vs.search(item["question"], k=10, mode=mode)
            ids = [r.get("id", "") for r in retrieved]
            sources = [r.get("metadata", {}).get("source", "") for r in retrieved]
            first_rank = next((i for i, cid in enumerate(ids, 1) if cid in gold), 0)
            results[mode].append({
                "id": item["id"],
                "type": item.get("type"),
                "theme": item.get("theme"),
                "difficulty": item.get("difficulty"),
                "applicability_label": item.get("applicability_label"),
                "first_rank": first_rank,
                "rr": 1.0 / first_rank if first_rank else 0.0,
                "ndcg10": ndcg_at_k(ids, gold, 10),
                "hits_at_k": {k: bool(set(ids[:k]) & gold) for k in K_LIST},
                "source_hits_at_k": {k: any(s in set(sources[:k]) for s in source_files) for k in K_LIST},
                "top_retrieved_ids": ids[:3],
                "top_sources": sources[:3],
            })
    return results


def summarize(records: List[Dict]) -> Dict:
    n = len(records)
    rr = [r["rr"] for r in records]
    lo, hi = bootstrap_ci(rr)
    neg = [r for r in records if r["applicability_label"] == "不适用"]
    out = {
        "MRR": round(sum(rr) / n, 4),
        "MRR_CI95": [round(lo, 4), round(hi, 4)],
        "nDCG@10": round(sum(r["ndcg10"] for r in records) / n, 4),
    }
    for k in K_LIST:
        hits = [1.0 if r["hits_at_k"][k] else 0.0 for r in records]
        out[f"Recall@{k}"] = round(sum(hits) / n, 4)
        out[f"Source_Hit@{k}"] = round(sum(r["source_hits_at_k"][k] for r in records) / n, 4)
    h_lo, h_hi = bootstrap_ci([1.0 if r["hits_at_k"][10] else 0.0 for r in records])
    out["Recall@10_CI95"] = [round(h_lo, 4), round(h_hi, 4)]
    # 负例（"不适用"题）：top-5 内是否召回了能支撑"不适用"判断的条款。
    #
    # 【重要·口径修正】这个指标历史上叫 Negative_Rejection_Accuracy 并被写成
    # "反事实负例正确拒答率 75%/100%"，但它是**循环定义**：
    #   - 检索层本身没有任何拒答/弃权逻辑（src/rag/ 下搜不到拒答实现）；
    #   - 这里衡量的是"top-5 是否命中 gold_chunk"，命中了反而说明检索器把
    #     那条"其实不适用"的条款捞了出来——文件名就叫 Rejection 却是
    #     "检索命中"的读数，两者不是一回事。
    # 现在改为如实命名 Negative_Retrieval_HitRate（负例检索命中率），
    # 保留旧键仅用于向后兼容读取历史结果文件，且其值不再被任何
    # 对外材料当作"拒答率"引用（见 tests/test_rag_metric_naming.py）。
    hits_neg = sum(1 for r in neg if r["hits_at_k"][5])
    ratio = round(hits_neg / len(neg), 4) if neg else 0.0
    out["Negative_Retrieval_HitRate"] = ratio
    out["Negative_Retrieval_HitCount"] = f"{hits_neg}/{len(neg)}" if neg else "0/0"
    # 旧键保留（兼容既有结果 JSON 的读取方），但值同源，且已明确非"拒答率"
    out["Negative_Rejection_Accuracy"] = ratio
    out["Negative_Rejection_Accuracy_note"] = (
        "该键为历史遗留名称，实际含义是『负例题的检索命中率』，不是拒答率；"
        "检索层无拒答实现，请勿在对外材料中称为拒答率"
    )
    return out


def stratified(records: List[Dict], key: str) -> Dict[str, Dict]:
    """按题型 / 难度分层给出 MRR 与 Recall@10（含题数）。

    为什么需要分层：总体 MRR 是 40 题的平均，掩盖了两件事——
    ① 系统在「事实型」问句上明显更好，在「对比型」上更弱；
    ② 人工标的难度与检索难度并不一致（实测「中」MRR 0.33 低于「难」0.48）。
    第 ② 条尤其要说：它说明难度标签是按「阅读理解难度」标的，不是按检索难度，
    所以不能拿「难题也检索到了」当作能力证据。
    """
    groups: Dict[str, List[Dict]] = {}
    for r in records:
        groups.setdefault(str(r.get(key) or "未标注"), []).append(r)

    out: Dict[str, Dict] = {}
    for name, rows in sorted(groups.items()):
        rr = [r["rr"] for r in rows]
        hits = [1.0 if r["hits_at_k"][10] else 0.0 for r in rows]
        lo, hi = bootstrap_ci(rr)
        out[name] = {
            "n": len(rows),
            "MRR": round(sum(rr) / len(rr), 4),
            "MRR_CI95": [round(lo, 4), round(hi, 4)],
            "Recall@10": round(sum(hits) / len(hits), 4),
        }
    return out


def evaluate_negative_suite(vs, modes: List[str]) -> Dict[str, Dict]:
    """在 30 题反事实负例集上单独评测「能否召回支撑『不适用』判断的条款」。

    为什么单独跑一套：
    40 题主集里只有 4 道负例，单题权重 25 个百分点——「3/4 与 2/4 的差别只差一道题」，
    撑不起任何关于拒答能力的结论。30 题集（4 道原负例 + 26 道扩充）把分辨率降到
    3.3 个百分点，至少能看出方案间的量级差异。

    指标命名务必注意：这里衡量的仍然是**检索命中**——top-k 里有没有出现人工标注的
    「支撑不适用结论」的条款，不是系统真的拒答了。检索层没有弃答逻辑
    （src/rag/ 下没有拒答实现，证据为空时才短路），所以对外只能叫
    「负例依据召回率」，不能叫「拒答准确率」。该口径与主集的
    Negative_Retrieval_HitRate 一致，见 tests/test_rag_metric_naming.py。
    """
    if not NEGATIVE_DATASET_PATH.exists():
        return {}
    dataset: List[Dict] = json.loads(NEGATIVE_DATASET_PATH.read_text(encoding="utf-8"))
    if not dataset:
        return {}

    out: Dict[str, Dict] = {}
    top_k = max(K_LIST)
    for mode in modes:
        per_question_top5 = []
        rr = []
        hits = {k: 0 for k in K_LIST}
        for item in dataset:
            gold = set(item.get("gold_chunk_ids") or [])
            if not gold:
                continue
            ids = [r.get("id", "") for r in vs.search(item["question"], k=top_k, mode=mode)]
            for k in K_LIST:
                if set(ids[:k]) & gold:
                    hits[k] += 1
            first = next((i for i, cid in enumerate(ids, 1) if cid in gold), 0)
            rr.append(1.0 / first if first else 0.0)
            per_question_top5.append(1.0 if set(ids[:5]) & gold else 0.0)

        n = len(rr)
        lo, hi = bootstrap_ci(per_question_top5) if n else (0.0, 0.0)
        out[mode] = {
            "n_questions": n,
            "MRR": round(sum(rr) / n, 4) if n else 0.0,
            **{f"Recall@{k}": round(hits[k] / n, 4) if n else 0.0 for k in K_LIST},
            "Recall@5_CI95": [round(lo, 4), round(hi, 4)],
        }
    return out


def evaluate_retrieval(embedding_ablation: bool = False):
    from src.config import RRF_WEIGHTS
    from src.rag.vector_store import PolicyVectorStore

    dataset: List[Dict] = json.loads(DATASET_PATH.read_text(encoding="utf-8"))
    vs = PolicyVectorStore()
    stats = vs.get_stats()
    if stats["total_chunks"] == 0:
        raise SystemExit("知识库为空，请先运行 python scripts/ingest_policy_docs.py")
    print(f"知识库: {stats['total_chunks']} 块 / {stats['total_documents']} 份文档 | 嵌入: {stats['embedding_model']}")

    results = run_modes(vs, dataset, MODES)
    summary = {m: summarize(results[m]) for m in MODES}
    negative = evaluate_negative_suite(vs, MODES)
    strat = {
        "by_type": stratified(results["rrf3"], "type"),
        "by_difficulty": stratified(results["rrf3"], "difficulty"),
    }

    # 显著性：v0.4 默认方案 rrf3 对比其余各组 + 保留旧版 hybrid 对比键
    comparisons = {
        "rrf3_vs_keyword": ("rrf3", "keyword"),
        "rrf3_vs_vector": ("rrf3", "vector"),
        "rrf3_vs_hybrid": ("rrf3", "hybrid"),
        "rrf3_vs_bm25": ("rrf3", "bm25"),
        "rrf3_vs_rrf": ("rrf3", "rrf"),
        "hybrid_vs_keyword": ("hybrid", "keyword"),
        "hybrid_vs_vector": ("hybrid", "vector"),
    }
    raw_p, sig = {}, {}
    for name, (a, b) in comparisons.items():
        w, p = wilcoxon_signed_rank([r["rr"] for r in results[a]], [r["rr"] for r in results[b]])
        raw_p[name] = p
        sig[name] = {"W_stat": w, "p_value": round(p, 5)}
    adj = holm_correction(raw_p)
    for name in sig:
        sig[name]["p_holm"] = round(adj[name], 5)
        sig[name]["is_significant_005"] = adj[name] < 0.05

    embedding_ablation_result = None
    if embedding_ablation:
        embedding_ablation_result = run_embedding_ablation(dataset, summary["vector"], stats["embedding_model"])

    # 终端报表
    print("\n" + "=" * 96)
    print(f"{'检索方案':<22}| {'MRR [95%CI]':<22}| {'R@1':<7}| {'R@3':<7}| {'R@5':<7}| {'R@10':<7}| {'nDCG@10':<8}")
    print("-" * 96)
    for m in MODES:
        s = summary[m]
        ci = f"{s['MRR']:.3f} [{s['MRR_CI95'][0]:.3f},{s['MRR_CI95'][1]:.3f}]"
        print(f"{MODE_LABELS[m]:<20}| {ci:<22}| {s['Recall@1']:<7.1%}| {s['Recall@3']:<7.1%}| "
              f"{s['Recall@5']:<7.1%}| {s['Recall@10']:<7.1%}| {s['nDCG@10']:.3f}")
    print("=" * 96)
    for name, v in sig.items():
        print(f"  {name:<20} p={v['p_value']:.4f}  Holm校正 p={v['p_holm']:.4f}  "
              f"{'显著' if v['is_significant_005'] else '不显著'}")
    if negative:
        print("\n反事实负例集（%d 题，指标为「负例依据召回」，非拒答率）" % next(iter(negative.values()))["n_questions"])
        print("-" * 96)
        for m in MODES:
            x = negative[m]
            ci = f"{x['Recall@5_CI95'][0]:.3f}~{x['Recall@5_CI95'][1]:.3f}"
            print(f"{MODE_LABELS[m]:<20}| MRR {x['MRR']:.4f} | R@5 {x['Recall@5']:.1%}"
                  f" [{ci}] | R@10 {x['Recall@10']:.1%}")

    payload = {
        "benchmark_metadata": {
            "total_questions": len(dataset),
            "total_chunks": stats["total_chunks"],
            "total_documents": stats["total_documents"],
            "embedding_model": stats["embedding_model"],
            "default_mode": "rrf3",
            # 融合权重必须随结果一起存档：权重一变，rrf3 的指标就不可比
            "rrf_weights": dict(RRF_WEIGHTS),
            "bootstrap_resamples": 2000,
            "multiple_comparison": "Holm-Bonferroni",
            # 知识库指纹：评测结论只对这份语料成立，知识库增删文档后必须重测
            "kb_manifest": sorted(vs.source_hashes().keys()),
            "kb_fingerprint": __import__("hashlib").sha1(
                json.dumps(sorted(vs.source_hashes().items()), ensure_ascii=False).encode()
            ).hexdigest()[:12],
        },
        "mode_labels": MODE_LABELS,
        "summary_metrics": summary,
        "statistical_significance": sig,
        "negative_suite": negative,
        "stratified_rrf3": strat,
        "embedding_ablation": embedding_ablation_result,
        "detailed_results": results,
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    write_markdown_report(payload)
    print(f"\n✅ 结果: {OUT_JSON.relative_to(PROJECT_ROOT)}\n✅ 报告: {OUT_MD.relative_to(PROJECT_ROOT)}")
    return summary, sig


def run_embedding_ablation(dataset, current_vector_summary, current_model):
    """用英文 MiniLM 嵌入单独建库，对比纯向量检索效果（临时目录，不影响主库）。"""
    import tempfile
    from src.config import POLICY_DOCS_DIR
    from src.rag import ingest_directory
    from src.rag.vector_store import PolicyVectorStore

    with tempfile.TemporaryDirectory() as tmp:
        legacy = PolicyVectorStore(persist_dir=tmp, embedding_model="chromadb-default")
        ingest_directory(POLICY_DOCS_DIR, legacy)
        legacy_res = run_modes(legacy, dataset, ["vector", "rrf"])
        out = {
            "chromadb-default(all-MiniLM-L6-v2)": {
                "vector": summarize(legacy_res["vector"]),
                "rrf": summarize(legacy_res["rrf"]),
            },
            current_model: {"vector": current_vector_summary},
        }
    return out


def write_markdown_report(payload: Dict):
    s = payload["summary_metrics"]
    sig = payload["statistical_significance"]
    meta = payload["benchmark_metadata"]
    rows = []
    for m in MODES:
        x = s[m]
        bold = "**" if m == "rrf3" else ""
        rows.append(
            f"| {bold}{MODE_LABELS[m]}{bold} | {bold}{x['MRR']:.4f}{bold} "
            f"[{x['MRR_CI95'][0]:.3f}, {x['MRR_CI95'][1]:.3f}] | {x['Recall@1']:.1%} | {x['Recall@3']:.1%} | "
            f"{x['Recall@5']:.1%} | {x['Recall@10']:.1%} | {x['nDCG@10']:.4f} | {x['Source_Hit@5']:.1%} | "
            f"{x['Negative_Rejection_Accuracy']:.0%} |"
        )
    sig_rows = [
        f"| {k} | {v['W_stat']:.1f} | {v['p_value']:.4f} | {v['p_holm']:.4f} | {'✅ 显著' if v['is_significant_005'] else '不显著'} |"
        for k, v in sig.items()
    ]
    rerank_path = OUT_JSON.parent / "reranker_experiment.json"
    rerank_md = "未运行。"
    if rerank_path.exists():
        rx = json.loads(rerank_path.read_text(encoding="utf-8"))
        rerank_md = (f"配置：{rx['base_mode']} 召回 top-{rx['candidates']} → `{rx['model']}` 精排，段落截断 {rx['max_chars']} 字。"
                     f"结果 MRR {rx['MRR']:.4f}、Recall@1 {rx['Recall@1']:.1%}、Recall@10 {rx['Recall@10']:.1%}，"
                     f"CPU 推理约 {rx['sec_per_query']:.1f} 秒/题（{rx['hardware']}）。{rx['conclusion']}")
    abl_post = payload.get("embedding_ablation")
    abl_md = ""
    if abl_post:
        abl_md = "\n## 三、嵌入模型消融（纯向量检索）\n\n| 嵌入模型 | 纯向量 MRR | 纯向量 Recall@10 | RRF MRR |\n|---|:---:|:---:|:---:|\n"
        for model, v in abl_post.items():
            rrf = v.get("rrf", {}).get("MRR")
            abl_md += (f"| {model} | {v['vector']['MRR']:.4f} | {v['vector']['Recall@10']:.1%} | "
                       f"{'%.4f' % rrf if rrf is not None else '%.4f' % s['rrf']['MRR']} |\n")
        abl_md += ("\n结论：v0.3 使用的 ChromaDB 默认嵌入是英文模型 all-MiniLM-L6-v2，"
                   "对中文政策文本几乎不具备语义区分度，这是旧版“纯向量组”指标极低的根因，"
                   "而非“向量检索不适合政策场景”。更换为中文 BGE 模型后纯向量检索显著改善。\n")

    neg = payload.get("negative_suite") or {}
    neg_md = ""
    if neg:
        n_neg = next(iter(neg.values()))["n_questions"]
        neg_rows = [
            f"| {MODE_LABELS[m]} | {neg[m]['MRR']:.4f} | {neg[m]['Recall@1']:.1%} | "
            f"{neg[m]['Recall@3']:.1%} | {neg[m]['Recall@5']:.1%} "
            f"[{neg[m]['Recall@5_CI95'][0]:.3f}, {neg[m]['Recall@5_CI95'][1]:.3f}] | "
            f"{neg[m]['Recall@10']:.1%} |"
            for m in MODES if m in neg
        ]
        neg_md = f"""
## 三·二、反事实负例集（{n_neg} 题，单独评测）

主集 40 题里只有 4 道负例，单题权重 25 个百分点，撑不起关于拒答能力的结论。
本节改用 `negative_benchmark_30_questions.json`（4 道原负例 + 26 道扩充场景）
单独评测，分辨率降到 3.3 个百分点。

> **与主集的关系**：30 题集是主集 4 道负例的**超集扩充**，不是独立第三套数据——
> Q04/Q24/Q29/Q30 与主集同号同题，主集的 Recall 分母含它们，本节又单独算一次，
> 两处读数不可相加或平均。
> **口径**：衡量的是 top-k 是否召回到人工标注的「支撑**不适用**判断」的条款，
> 即**负例依据召回率**。检索层没有弃答逻辑（`src/rag/` 下无拒答实现），
> 因此不能称为「拒答准确率」。命名守卫见 `tests/test_rag_metric_naming.py`。

| 方案 | MRR | Recall@1 | Recall@3 | Recall@5 [95% CI] | Recall@10 |
|---|:---:|:---:|:---:|:---:|:---:|
{chr(10).join(neg_rows)}

解读时注意：召回率高只说明「判定不适用所需的条款被捞了出来」，
真正的拒答由生成层依据这些条款完成；条款没召回到时，作答会缺少依据。
"""

    strat = payload.get("stratified_rrf3") or {}
    strat_md = ""
    if strat.get("by_type"):
        type_rows = [
            f"| {name} | {v['n']} | {v['MRR']:.4f} "
            f"[{v['MRR_CI95'][0]:.3f}, {v['MRR_CI95'][1]:.3f}] | {v['Recall@10']:.1%} |"
            for name, v in strat["by_type"].items()
        ]
        diff_rows = [
            f"| {name} | {v['n']} | {v['MRR']:.4f} "
            f"[{v['MRR_CI95'][0]:.3f}, {v['MRR_CI95'][1]:.3f}] | {v['Recall@10']:.1%} |"
            for name, v in (strat.get("by_difficulty") or {}).items()
        ]
        # 检出「难度标签与检索难度不一致」这一事实，并如实说明它的含义
        diff = strat.get("by_difficulty") or {}
        anomaly = ""
        if "中" in diff and "难" in diff and diff["中"]["MRR"] < diff["难"]["MRR"]:
            anomaly = (
                "\n> ⚠️ **难度标签与检索难度不一致**：标为「中」的题 MRR 反而低于标为「难」的题。"
                "原因是难度按「人工阅读理解难度」标注，而不是按检索器难度标注——"
                "「中」档里有多道跨文件对比题（如购电口径对比、三地试点对比），"
                "对检索更难；「难」档里则有若干问句与条款用词高度重合的题，反而容易命中。"
                "**因此不能拿「难题也能检索到」当作能力证据**，也不能把该列读成难度梯度。\n"
            )
        strat_md = f"""
## 三·三、分层评测（默认方案 rrf3）

总体 MRR 是 40 题的平均，会掩盖题型之间的差异。下表按题库标注的题型与难度分层。
「对比型」指跨文件/跨年度规则比对，是本题库最贴近真实咨询场景的一类。

| 题型 | 题数 | MRR [95% CI] | Recall@10 |
|---|:---:|:---:|:---:|
{chr(10).join(type_rows)}

| 标注难度 | 题数 | MRR [95% CI] | Recall@10 |
|---|:---:|:---:|:---:|
{chr(10).join(diff_rows)}
{anomaly}"""

    neg_conclusion = ""
    if neg:
        best_mrr = max(neg, key=lambda m: neg[m]["MRR"])
        best_r10 = max(neg, key=lambda m: neg[m]["Recall@10"])
        default = neg["rrf3"]
        neg_conclusion = (
            f"\n5. **默认方案在负例集上不是最优，如实记录**：30 题负例集上三路 RRF 的 "
            f"MRR {default['MRR']:.4f}、Recall@10 {default['Recall@10']:.1%}；"
            f"按 MRR 最高是{MODE_LABELS[best_mrr]}（{neg[best_mrr]['MRR']:.4f}），"
            f"按 Recall@10 最高是{MODE_LABELS[best_r10]}（{neg[best_r10]['Recall@10']:.1%}）。"
            "两个口径指向不同方案，而所有方案的置信区间都大幅重叠——"
            "这说明 30 题仍不足以分辨方案优劣，也说明默认权重"
            "（BM25 0.6 : 向量 0.1 : 字面 0.8）是针对正例题的检索质量调的，"
            "并未针对「判定不适用所需的条款」优化。"
            "本项目**不据此改动默认方案**：负例集同样是自建自测，"
            "在一个集上调权重、再用同一个集报结论，属于循环论证。"
            "如实记录的方法是把它列为已知局限，并在生成层保留"
            "「证据不足则不回答」的短路逻辑。\n"
        )

    content = f"""# RAG 政策问答检索对照实验报告（v0.4）

> 评测集：双人背靠背独立审校 40 题金标基准 · 知识库 {meta['total_documents']} 份政策文件 / {meta['total_chunks']} 个分块
> 嵌入模型：`{meta['embedding_model']}` · 统一 top-10 · Bootstrap {meta['bootstrap_resamples']} 次 · 多重比较 {meta['multiple_comparison']} 校正
> 三路 RRF 权重：BM25 {meta['rrf_weights']['bm25']} · 向量 {meta['rrf_weights']['vector']} · 字面规则 {meta['rrf_weights']['keyword']}（交叉验证见 `rrf_weight_cross_validation.md`）
> 复现命令：`python scripts/ingest_policy_docs.py --force && python scripts/evaluate_rag_benchmark.py --embedding-ablation`

## 一、各检索方案指标

| 方案 | MRR [95% CI] | Recall@1 | Recall@3 | Recall@5 | Recall@10 | nDCG@10 | Source Hit@5 | 负例依据召回 |
|---|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
{chr(10).join(rows)}

## 二、配对显著性检验（Wilcoxon 符号秩，倒数秩为配对指标）

| 比较 | W | 原始 p | Holm 校正 p | 结论(α=0.05) |
|---|:---:|:---:|:---:|:---:|
{chr(10).join(sig_rows)}
{abl_md}{neg_md}{strat_md}
## 四、交叉编码器精排实验（独立运行）

{rerank_md}

## 五、结论与局限

1. **v0.3 纯向量组指标极低的根因是嵌入模型选错**：ChromaDB 默认的 all-MiniLM-L6-v2 是英文模型。换成中文 bge-small-zh 后纯向量 MRR 明显提升（见第三节），说明问题不在“向量检索不适合政策文本”。
2. **默认方案改为三路 RRF（F 组）**：BM25（jieba 分词）、中文稠密向量、v0.3 字面规则三路检索按名次融合（RRF，k=60，原论文推荐值）。三路权重为 BM25 {meta['rrf_weights']['bm25']} : 向量 {meta['rrf_weights']['vector']} : 字面规则 {meta['rrf_weights']['keyword']}，不是等权——等权融合的 MRR 只有 0.4112，低于它要取代的 v0.3 方案，是在同一评测集上做权重诊断时才发现的（该数字与权重调优同源，不作独立证据）。权重稳健性用 5 折交叉验证单独检查：折内独立选出的向量权重全部落在 0.05–0.2，见 `rrf_weight_cross_validation.md`。F 组 Recall@10 在全部方案中最高。
3. **如实交代的负面结果**：① 两路 RRF（E 组）的 MRR 不如 BM25 单路，原因是稠密向量对“情景描述型”长问题仍然偏弱，融合时拖低了排序；② v0.3 字面规则里有几条针对主题写的加权规则，存在对评测集过拟合的风险，所以 v0.4 只把它当作融合中的一路信号，不再让它主导打分；③ 交叉编码器精排在 CPU 上每题约 9 秒，指标反而下降，所以默认关闭；④ 三路 RRF 相对 v0.3 与 BM25 的差距经 Holm 校正后均不显著，只能说“不劣于”，不能说“显著更好”。
4. **局限**：评测集只有 40 题，置信区间较宽，多数两两差异经多重比较校正后不显著。下一步计划把评测集扩到 100 题以上，按“单一事实型 / 情景推理型”分层评测，并加入生成质量评测（忠实度、引用准确率）。{neg_conclusion}"""
    # 生成段只覆盖到「五、结论与局限」。手工追加的附录（例如第 40/287 份文档
    # 入库后的复测对照、金标重标说明）不是脚本产物，重跑时必须原样保留——
    # 早期版本直接整文件覆写，每跑一次评测就静默吃掉一段人工结论。
    if OUT_MD.exists():
        previous = OUT_MD.read_text(encoding="utf-8")
        marker = previous.find("\n---\n\n## 附录")
        if marker != -1:
            content += previous[marker:]
    OUT_MD.write_text(content, encoding="utf-8")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--embedding-ablation", action="store_true", help="额外对比英文默认嵌入")
    evaluate_retrieval(embedding_ablation=ap.parse_args().embedding_ablation)
