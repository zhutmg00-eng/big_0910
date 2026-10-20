"""双人背靠背标注一致性统计。

只统计「编码型」字段（答案要点判定、适用性标签），不统计自由文本的
判定说明——两份标注的自由文本本来就应当用各自的话写，逐字相同反而是抄写。

用法：python scripts/check_annotation_agreement.py
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVIEW_DIR = PROJECT_ROOT / "docs" / "rag_benchmark" / "review"
FILE_A = REVIEW_DIR / "标注表_标注者A.csv"
FILE_B = REVIEW_DIR / "标注表_标注者B.csv"
OUT_JSON = REVIEW_DIR / "annotation_agreement.json"

CODED_FIELDS = {
    "答案要点判定": "[核对]答案要点判定(✓/✗/?)",
    "适用性标签判定": "[标签]适用性判定(同意/不同意)",
}


def load(path: Path) -> dict[str, dict[str, str]]:
    rows = list(csv.reader(io.open(path, encoding="utf-8-sig")))
    header = [h.strip().lstrip("\ufeff") for h in rows[0]]
    out = {}
    for r in rows[1:]:
        if r and r[0].strip():
            out[r[0].strip()] = dict(zip(header, r))
    return out


def cohens_kappa(a: list[str], b: list[str]) -> tuple[float, float, bool]:
    """返回 (kappa, 观测一致率, 是否退化)。类别零变异时 kappa 数学上无定义。"""
    n = len(a)
    agree = sum(1 for x, y in zip(a, b) if x == y) / n
    cats = sorted(set(a) | set(b))
    pe = sum((a.count(c) / n) * (b.count(c) / n) for c in cats)
    degenerate = pe >= 1.0 - 1e-12
    if degenerate:
        return 1.0, agree, True
    return (agree - pe) / (1 - pe), agree, False


def main():
    A, B = load(FILE_A), load(FILE_B)
    common = sorted(set(A) & set(B))
    if not common:
        raise SystemExit("两份标注表没有共同题号，无法统计")
    print(f"共同题数: {len(common)}（A={len(A)}，B={len(B)}）")

    payload = {"n_items": len(common), "n_annotator_a": len(A), "n_annotator_b": len(B), "fields": {}}
    for label, col in CODED_FIELDS.items():
        a_vals = [A[q].get(col, "").strip() for q in common]
        b_vals = [B[q].get(col, "").strip() for q in common]
        kappa, agree, degenerate = cohens_kappa(a_vals, b_vals)
        dist = {v: a_vals.count(v) for v in sorted(set(a_vals))}
        payload["fields"][label] = {
            "agreement_rate": round(agree, 4),
            "cohens_kappa": round(kappa, 4),
            "kappa_is_degenerate": degenerate,
            "value_distribution_annotator_a": dist,
            "disagreements": [q for q in common if A[q].get(col, "").strip()
                              != B[q].get(col, "").strip()],
        }
        status = (
            "Kappa 退化：判定类别零变异，数学上恒为 1，不能作为一致性证据"
            if degenerate else f"Kappa = {kappa:.4f}"
        )
        print(f"  {label}: 一致率 {agree:.1%}（{dist}）→ {status}")

    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n✅ {OUT_JSON.relative_to(PROJECT_ROOT)}")
    return payload


if __name__ == "__main__":
    main()
    sys.exit(0)
