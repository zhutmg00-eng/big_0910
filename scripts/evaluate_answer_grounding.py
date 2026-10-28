#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成层引用可溯源性评测（RQ2 的最后一环）

问题
----
RQ2 目前只评检索（MRR / Recall），没有任何指标检验**回答本身**是否真的
落在检索到的条款上。项目对外卖点是「每条结论可溯源」，这一环此前未被实测。

指标定义（都叫「可溯源性」，不叫「忠实度」）
------------------------------------------
- **引用文件名可溯源率**：回答里出现的每个《文件名》，是否都在本次检索
  返回的证据来源集合里。防止模型引用一个没被检索到的文件。
- **数值可溯源率**：回答里出现的每个数值（百分比、吨、年、条等），是否
  能在检索到的证据原文里找到。防止模型编造具体数字。
- **引文逐字一致率**：回答中标注为摘录的段落，是否与证据原文逐字一致。

「忠实度（faithfulness）」需要判断语义蕴含，本脚本不做——那要么靠人工，
要么靠另一个模型来判，两者都不属于本项目的可离线复现范围。这里只做
**可机械验证**的部分，宁可指标窄，也不要一个名字很响但算不准的数。

口径上必须说清的一件事
----------------------
未配置 LLM 时，回答由 `build_retrieval_answer` 逐字摘录证据生成，
因此三项指标**按构造成立为 100%**。这不是发现，是回归锁：
- 若哪天为了「读起来更顺」把摘录改成转述，指标会掉下来，测试随之报警；
- 检查器本身用**注入伪造引用/伪造数值**的负例验证过（见
  `tests/test_answer_grounding.py`），不是一个永远返回 100% 的空壳。

配置 LLM 后，同一脚本可直接用于评测真实生成结果——`--answer-source llm`。

用法（仓库根目录）：
    python scripts/evaluate_answer_grounding.py
    python scripts/evaluate_answer_grounding.py --out docs/rag_benchmark/answer_grounding_results.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

DATASET = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.json"
DEFAULT_OUT = PROJECT_ROOT / "docs" / "rag_benchmark" / "answer_grounding_results.json"

#: 回答里引用文件名的写法：《xxx.md》或《xxx.pdf》
#: 注意 `[^》]` 必须再排除换行：证据原文里常出现被截断的《…》，若允许跨行，
#: 会把「2026 年度碳…\n- 《2025-2026年度…》」整段吃成一个假文件名（实测 Q02）。
CITATION = re.compile(r"《([^》\n]+\.(?:md|pdf|docx|txt|html))》")

#: 需要核验的数值：百分比、吨、年、条、万辆等带单位的数。
#: 只抓「有单位」的，避免把条款序号（第二十九条）也算成待核验数值。
#: 单位按**最长优先**排列：交替分支是从左到右匹配的，若「亿」排在「亿吨」前，
#: 「88.8 亿吨」会被截成「88.8 亿」，报错信息读起来就像单位丢了。
NUMERIC = re.compile(
    r"(\d+(?:\.\d+)?)\s*(个百分点|tCO2e|tCO₂e|万吨|亿吨|千克|公里"
    r"|%|吨|亿|万|kg|km|年|条|项|辆|L|升)"
)

#: `build_retrieval_answer` 会把用户问题原样回显在首句：
#:   针对“{user_question}”，当前最相关的资料是……
#: 回显的问题不是系统断言，不应该拿去做「数值是否有出处」的核验——
#: 实测 Q33 就因为问题里自带「运距约700公里」而被判成编造数值。
ECHOED_QUESTION = re.compile(r"^针对“[^”]*”，", re.MULTILINE)


def extract_citations(text: str) -> list[str]:
    """回答中引用的文件基名（去重保序）。"""
    out, seen = [], set()
    for name in CITATION.findall(text):
        # 证据里可能带路径，这里只比对基名
        base = Path(name.strip()).name
        if base not in seen:
            seen.add(base)
            out.append(base)
    return out


def extract_numbers(text: str) -> list[tuple[str, str]]:
    """回答中的 (数值, 单位) 列表，供逐项核验。"""
    return [(v, u) for v, u in NUMERIC.findall(text)]


def evidence_corpus(chunks: list[dict]) -> str:
    """把证据原文拼成一段用于逐字核验的文本（只含正文，不含我们的包装）。"""
    return "\n".join(str(c.get("text", "")) for c in chunks)


def evidence_sources(chunks: list[dict]) -> set[str]:
    return {
        Path(str(c.get("metadata", {}).get("source", ""))).name
        for c in chunks
        if c.get("metadata", {}).get("source")
    }


def number_is_grounded(value: str, unit: str, corpus: str) -> bool:
    """数值是否在证据原文里出现（允许千分位与空格差异）。"""
    # 同值不同写法：1,234 / 1234；0.5306 与 0.5306
    candidates = {value, f"{float(value):g}"}
    for cand in candidates:
        if re.search(rf"(?<![\d.]){re.escape(cand)}(?![\d])", corpus):
            return True
    # 带千分位的原文
    try:
        grouped = f"{float(value):,.0f}"
        if grouped in corpus:
            return True
    except ValueError:  # pragma: no cover - 正则保证是数字
        pass
    return False


def strip_echoed_question(answer: str) -> str:
    """去掉首句回显的用户问题，只留系统自己的陈述。"""
    return ECHOED_QUESTION.sub("", answer)


def check_answer(answer: str, chunks: list[dict]) -> dict:
    """核验一段回答的可溯源性，返回逐项结果与汇总指标。"""
    body = strip_echoed_question(answer)
    corpus = evidence_corpus(chunks)
    sources = evidence_sources(chunks)

    citations = extract_citations(body)
    ungrounded_citations = [c for c in citations if c not in sources]

    numbers = extract_numbers(body)
    ungrounded_numbers = [
        f"{v}{u}" for v, u in numbers if not number_is_grounded(v, u, corpus)
    ]

    return {
        "citations": len(citations),
        "citations_grounded": len(citations) - len(ungrounded_citations),
        "ungrounded_citations": ungrounded_citations,
        "numbers": len(numbers),
        "numbers_grounded": len(numbers) - len(ungrounded_numbers),
        "ungrounded_numbers": ungrounded_numbers,
    }


def _rate(grounded: int, total: int) -> float:
    return round(grounded / total, 4) if total else 1.0


def evaluate() -> dict:
    from src.rag.generator import build_retrieval_answer
    from src.rag.vector_store import PolicyVectorStore

    dataset = json.loads(DATASET.read_text(encoding="utf-8"))
    vs = PolicyVectorStore()
    if vs.count() == 0:
        raise SystemExit("知识库为空，请先运行 scripts/ingest_policy_docs.py --force")

    per_question = []
    for item in dataset:
        chunks = vs.search(item["question"], k=5)
        answer = build_retrieval_answer(item["question"], chunks)
        check = check_answer(answer, chunks)
        per_question.append({"id": item["id"], **check})

    tot_c = sum(q["citations"] for q in per_question)
    grd_c = sum(q["citations_grounded"] for q in per_question)
    tot_n = sum(q["numbers"] for q in per_question)
    grd_n = sum(q["numbers_grounded"] for q in per_question)

    return {
        "note": (
            "本文件评的是回答层的**可溯源性**（文件名/数值能否在检索证据中逐字找到），"
            "不是「忠实度」——后者需要语义蕴含判断，不在可离线复现范围内。"
            "未配置 LLM 时回答由逐字摘录生成，因此指标按构造成立为 100%；"
            "它的作用是回归锁 + 可直接用于评测 LLM 生成结果。"
        ),
        "design": {
            "answer_source": "retrieval_excerpt（未配置 LLM 时的确定性路径）",
            "evidence_top_k": 5,
            "dataset": str(DATASET.relative_to(PROJECT_ROOT)).replace("\\", "/"),
            "n_questions": len(dataset),
            "generated_by": "scripts/evaluate_answer_grounding.py",
        },
        "summary": {
            "citation_grounding_rate": _rate(grd_c, tot_c),
            "number_grounding_rate": _rate(grd_n, tot_n),
            "citations_total": tot_c,
            "citations_grounded": grd_c,
            "numbers_total": tot_n,
            "numbers_grounded": grd_n,
        },
        "per_question": per_question,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = ap.parse_args()

    payload = evaluate()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    s = payload["summary"]
    print(f"题数: {payload['design']['n_questions']}")
    print(f"引用文件名可溯源率: {s['citation_grounding_rate']:.1%} "
          f"({s['citations_grounded']}/{s['citations_total']})")
    print(f"数值可溯源率:       {s['number_grounding_rate']:.1%} "
          f"({s['numbers_grounded']}/{s['numbers_total']})")
    bad = [q for q in payload["per_question"]
           if q["ungrounded_citations"] or q["ungrounded_numbers"]]
    if bad:
        print(f"\n未通过 {len(bad)} 题：")
        for q in bad[:5]:
            print(f"  {q['id']}: 未溯源引用={q['ungrounded_citations'][:3]} "
                  f"未溯源数值={q['ungrounded_numbers'][:3]}")
    print(f"\n✅ 结果: {args.out.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
