"""对外声称的数字必须与数据台账一致。

本项目历史上出现过同一数字三种口径名（4.23% 被称"全样本 MAPE"/"等权 MAPE"/"加权"）、
以及图上的误差区间（2.88%~5.20%）与正文（1.66%~7.27%）互相矛盾的情况。
本文件把「对外声称值」与「docs/derived_metrics.json 台账」锁在一起，
任何一侧漂移都会让测试失败，从而在提交前就暴露出来。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
METRICS = json.loads((ROOT / "docs" / "derived_metrics.json").read_text(encoding="utf-8"))


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def test_mape_claims_match_ledger():
    """README/论文里的 4.23% 与 2.38% 必须等于台账算出的值。"""
    mape = METRICS["mape"]
    assert mape["n_cases"] == 4
    expected_equal = mape["equal_weight_pct"]
    expected_weighted = mape["emission_weight_pct"]

    paper = _read("docs/academic_paper.md")
    assert f"{expected_equal}%" in paper or f"{expected_equal}\\%" in paper, (
        f"论文未出现台账等权 MAPE {expected_equal}%"
    )
    assert f"{expected_weighted}%" in paper or f"{expected_weighted}\\%" in paper, (
        f"论文未出现台账加权 MAPE {expected_weighted}%"
    )


def test_error_range_claims_match_ledger():
    """论文中声称的误差区间必须与台账的 min/max 完全一致。"""
    mape = METRICS["mape"]
    lo, hi = mape["min_pct"], mape["max_pct"]
    paper = _read("docs/academic_paper.md")

    # 论文写法为 $+1.66\% \sim +7.27\%$，故需允许 \sim 与 LaTeX 转义百分号
    pattern = (
        rf"\+?{re.escape(str(lo))}\s*\\?%\s*"
        rf"(?:~|～|-|\\sim)\s*"
        rf"\+?{re.escape(str(hi))}"
    )
    assert re.search(pattern, paper), (
        f"论文未出现与台账一致的误差区间 {lo}%~{hi}%"
    )


def test_no_stale_error_range_in_paper():
    """早期草稿残留的错误区间（2.88%/5.20%）不得再出现在论文中。"""
    paper = _read("docs/academic_paper.md")
    for stale in ("2.88", "5.20%"):
        assert stale not in paper, f"论文仍残留早期草稿数值 {stale}"


def test_vehicle_total_claims_consistent():
    """论文与说明书引用的车辆总数必须等于台账合计。"""
    total = METRICS["mape"]["vehicles_total"]
    expected = f"{total:,}"
    for rel in ("docs/academic_paper.md", "docs/real_fleet_validation_report.md"):
        text = _read(rel)
        assert expected in text, f"{rel} 未出现台账车辆总数 {expected}"


def test_no_sample_size_confusion_claim():
    """不得把 51,990 辆当作「实测样本量」——它是覆盖车辆数。"""
    paper = _read("docs/academic_paper.md")
    # 论文必须显式声明观测单元是 n=4 的车队级而非逐车
    assert "n=4" in paper or "n = 4" in paper, "论文未声明车队级观测单元 n=4"


def test_case_level_values_match_ledger():
    """论文表 4 的每个案例误差必须逐一对上台账。"""
    paper = _read("docs/academic_paper.md")
    for case in METRICS["fleet_cases"]:
        err = case["rel_err_pct"]
        sign = "+" if err >= 0 else ""
        token = f"{sign}{err}%"
        assert token in paper, f"论文表 4 缺少案例 {case['id']} 的误差 {token}"


# ---------- 图表产物：数字必须与台账一致，且不得有早期草稿残留 ----------

STALE_FIGURE_CLAIMS = ("2.88", "5.20", "高稳定性")


def test_figure_artifacts_render_ledger_range():
    """fig1 的结论条必须渲染台账区间；若模板用普通字符串会被原样写出 \u007bERR_LO\u007d。"""
    svg = _read("docs/artifacts/fig1_rq1_real_fleet_validation.svg")
    lo, hi = METRICS["mape"]["min_pct"], METRICS["mape"]["max_pct"]
    assert f"[+{lo}%, +{hi}%]" in svg, (
        f"fig1 未渲染台账偏差区间 [+{lo}%, +{hi}%]，检查模板是否为 f-string"
    )


def test_figure_artifacts_have_no_unrendered_placeholders():
    """占位符被原样写出说明该段字符串漏了 f 前缀。"""
    for rel in (
        "docs/artifacts/fig1_rq1_real_fleet_validation.svg",
        "docs/artifacts/fig2_rq2_rag_benchmark_comparison.svg",
        "docs/artifacts/fig3_rq3_sensitivity_heatmap.svg",
        "docs/artifacts/all_charts_dashboard.html",
    ):
        text = _read(rel)
        for token in ("{ERR_LO", "{ERR_HI", "{MAPE_EQ", "{MAPE_WT", "{LF_NO_BIAS", "{KB_DOCS"):
            assert token not in text, f"{rel} 仍含未渲染占位符 {token}"


def test_figure_artifacts_have_no_stale_claims():
    """早期草稿的 2.88%/5.20%/「高稳定性」不得重新出现在图表产物中。"""
    for rel in (
        "docs/artifacts/fig1_rq1_real_fleet_validation.svg",
        "docs/artifacts/fig1_rq1_real_fleet_validation.html",
        "docs/artifacts/all_charts_dashboard.html",
    ):
        text = _read(rel)
        for stale in STALE_FIGURE_CLAIMS:
            assert stale not in text, f"{rel} 仍含早期草稿数值/表述 {stale}"


def test_dashboard_kb_badge_matches_actual_corpus():
    """展板上的知识库规模徽标必须来自运行时实测，而不是写死的 37/268 旧快照。"""
    dashboard = _read("docs/artifacts/all_charts_dashboard.html")
    assert "37 份法规" not in dashboard, "展板仍使用 v0.4 旧快照的 37 份法规"
    assert "268 Chunks" not in dashboard, "展板仍使用 v0.4 旧快照的 268 Chunks"

    # 若知识库已建，徽标必须与 PolicyVectorStore.count() 一致
    try:
        import sys

        sys.path.insert(0, str(ROOT))
        from src.rag.vector_store import PolicyVectorStore

        actual = int(PolicyVectorStore().count())
    except Exception:
        return  # 未建库时跳过精确比对，仅做旧值守卫

    assert f"{actual} Chunks" in dashboard, (
        f"展板徽标与实测块数 {actual} 不一致"
    )
