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
