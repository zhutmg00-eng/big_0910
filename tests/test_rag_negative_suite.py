"""30 题反事实负例集的评测必须真的跑起来，且口径如实。

背景（2026-10-27）：
`negative_benchmark_30_questions.json` 早已存在（4 道原负例 + 26 道扩充），
但**没有任何脚本读取它**——它只是打包进交付物的一个文件，从未产出过指标。
主集 40 题里只有 4 道负例，单题权重 25 个百分点，撑不起任何关于
「能否召回支撑『不适用』判断的条款」的结论。

把 30 题集接进 `evaluate_rag_benchmark.py` 之后，测出一个与主集不一致的结果：
默认三路 RRF 在负例集上按 MRR 不是最优。这类负面结论必须原样保留在报告里
（而不是调参调到好看为止），因此本文件同时锁住「指标确实算出来了」与
「报告里如实写了这个不一致」。

命名口径：这里衡量的是**检索命中**，不是拒答。检索层没有弃答逻辑
（见 tests/test_rag_metric_naming.py），任何材料都不得称其为「拒答准确率」。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
NEG_DATASET = ROOT / "docs" / "rag_benchmark" / "negative_benchmark_30_questions.json"
RESULTS = ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json"
REPORT = ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_report.md"
EVAL_SCRIPT = ROOT / "scripts" / "evaluate_rag_benchmark.py"


def _results() -> dict:
    if not RESULTS.exists():
        pytest.skip("评测结果尚未生成")
    return json.loads(RESULTS.read_text(encoding="utf-8"))


def test_eval_script_actually_reads_negative_dataset() -> None:
    """脚本必须真正引用 30 题集，否则它只是躺在仓库里的一个死文件。"""
    src = EVAL_SCRIPT.read_text(encoding="utf-8")
    assert "negative_benchmark_30_questions.json" in src, (
        "评测脚本没有引用 30 题负例集，负例指标仍无处产生"
    )
    assert "evaluate_negative_suite" in src


@pytest.mark.parametrize("mode", ["keyword", "vector", "hybrid", "bm25", "rrf", "rrf3"])
def test_every_mode_has_negative_metrics(mode: str) -> None:
    """六种检索方案都要在负例集上有读数，否则无法横向比较。"""
    neg = _results().get("negative_suite") or {}
    assert mode in neg, f"结果 JSON 缺少 {mode} 的负例指标：{sorted(neg)}"
    row = neg[mode]
    assert row["n_questions"] == 30, f"{mode} 的负例题数应为 30，实际 {row['n_questions']}"
    for key in ("MRR", "Recall@1", "Recall@3", "Recall@5", "Recall@10", "Recall@5_CI95"):
        assert key in row, f"{mode} 缺少 {key}"
    assert 0.0 <= row["MRR"] <= 1.0
    assert 0.0 <= row["Recall@10"] <= 1.0


def test_negative_dataset_matches_dataset_size() -> None:
    """数据集本身是 30 题，与结果里的分母一致。"""
    data = json.loads(NEG_DATASET.read_text(encoding="utf-8"))
    assert len(data) == 30
    assert all(q.get("applicability_label") == "不适用" for q in data), (
        "负例集里出现了 non-不适用 的题，会污染分母"
    )
    assert all(q.get("gold_chunk_ids") for q in data)


def test_recall_is_monotonic_in_k() -> None:
    """Recall@k 必须随 k 单调不减，否则说明取样或计数写错了。"""
    for mode, row in (_results().get("negative_suite") or {}).items():
        values = [row[f"Recall@{k}"] for k in (1, 3, 5, 10)]
        assert values == sorted(values), f"{mode} 的 Recall@k 非单调：{values}"


def test_report_states_default_is_not_best_on_negative_suite() -> None:
    """默认方案在负例集上不是最优——这条负面结论必须留在报告里。

    如果将来真的改进了默认方案，把这段改写为新结论即可，但不能删掉
    「曾出现过不一致」这个事实：它在答辩时会被问到。
    """
    text = REPORT.read_text(encoding="utf-8")
    assert "负例集上不是最优" in text, "报告没有如实记录负例集上的不利结果"
    neg = _results()["negative_suite"]
    assert neg["rrf3"]["MRR"] < max(v["MRR"] for v in neg.values()), (
        "负例集上默认方案已变成 MRR 最优，报告里的负面结论需要更新"
    )


def test_report_never_calls_it_refusal_accuracy() -> None:
    """负例小节不得把检索命中率说成「拒答准确率」。"""
    text = REPORT.read_text(encoding="utf-8")
    section = text.split("## 三·二", 1)
    if len(section) < 2:
        pytest.skip("报告尚未包含负例小节")
    body = section[1].split("## 四", 1)[0]
    for banned in ("拒答准确率", "拒答率"):
        for line in body.splitlines():
            if banned not in line:
                continue
            # 允许出现在「不能称为…」这类否定句里
            assert any(neg in line for neg in ("不能称为", "不是", "非拒答", "≠")), (
                f"负例小节把检索命中写成了{banned}：{line.strip()[:120]}"
            )


def test_negative_section_has_ci() -> None:
    """30 题的置信区间必须写出来，否则读者会高估精度。"""
    text = REPORT.read_text(encoding="utf-8")
    if "## 三·二" not in text:
        pytest.skip("报告尚未包含负例小节")
    body = text.split("## 三·二", 1)[1].split("## 四", 1)[0]
    assert re.search(r"\[0\.\d{3},\s*0\.\d{3}\]", body), "负例表缺少 95% 置信区间"


# ---------------------------------------------------------------- 与主集的关系（I-3）

class TestSupersetRelationshipIsDisclosed:
    """30 题集是主集 4 道负例的超集，不是独立第三套数据。

    这个关系一旦不说清，读者会把「主集 50%、负例集 30%」当成两套互相印证的
    证据，进而得出「两套数据结论不一致」的错误判断——实际上是同一批题在
    不同分母下的两个读数。
    """

    MAIN_DATASET = ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.json"
    NEG_MD = ROOT / "docs" / "rag_benchmark" / "negative_benchmark_30_questions.md"

    def _overlap(self) -> set[str]:
        main = json.loads(self.MAIN_DATASET.read_text(encoding="utf-8"))
        neg = json.loads(NEG_DATASET.read_text(encoding="utf-8"))
        return {q["id"] for q in main} & {q["id"] for q in neg}

    def test_overlap_actually_exists(self) -> None:
        """若哪天两份数据不再重叠，下面几条披露要求就该重新评估。"""
        assert self._overlap() == {"Q04", "Q24", "Q29", "Q30"}

    def test_report_says_superset_not_independent(self) -> None:
        text = REPORT.read_text(encoding="utf-8")
        if "## 三·二" not in text:
            pytest.skip("报告尚未包含负例小节")
        body = text.split("## 三·二", 1)[1].split("## 四", 1)[0]
        assert "超集" in body, "报告没有说明 30 题集是主集负例的超集"
        assert "独立评测" not in body, (
            "报告仍称其为「独立评测」——其中 4 题与主集同号同题，会误导读者"
        )
        assert "不可相加或平均" in body, "缺少「两处读数不可合并」的提示"

    def test_negative_dataset_md_says_superset(self) -> None:
        text = self.NEG_MD.read_text(encoding="utf-8")
        assert "超集" in text, "负例集说明文件没有交代它与主集的关系"

    def test_negative_dataset_md_does_not_claim_stale_kb_as_current(self) -> None:
        """旧库规模可以出现在「构建时」的语境里，但不能当作当前状态陈述。"""
        text = self.NEG_MD.read_text(encoding="utf-8")
        for line in text.splitlines():
            if "37 份" not in line and "268" not in line:
                continue
            assert any(m in line for m in ("构建时", "当时", "旧库", "此后")), (
                f"负例集说明把旧库规模当作当前状态陈述：{line.strip()[:120]}"
            )

    def test_readme_separates_frozen_snapshot_from_retest(self) -> None:
        """README 不得把 39/281 冻结快照的 MRR 说成「当前知识库」的读数。"""
        text = (ROOT / "README.md").read_text(encoding="utf-8")
        for line in text.splitlines():
            if "0.492" not in line and "0.478" not in line:
                continue
            if "当前知识库上" in line and "0.492" in line:
                raise AssertionError(
                    f"README 把冻结快照读数当作当前读数：{line.strip()[:140]}"
                )


# ---------------------------------------------------------------- 分层评测（I-9）

class TestStratifiedMetrics:
    """总体 MRR 会掩盖题型与难度之间的差异，分层表必须真的算出来。

    这一节的存在本身就带一个负面结论：人工标的「难度」与检索难度不一致
    （「中」档 MRR 低于「难」档）。它必须留在报告里——不能因为读起来
    不顺就删掉，也不能把该列当成难度梯度来宣传。
    """

    def _strat(self) -> dict:
        return _results().get("stratified_rrf3") or {}

    def test_has_both_strata(self) -> None:
        strat = self._strat()
        assert strat.get("by_type"), "缺少按题型分层"
        assert strat.get("by_difficulty"), "缺少按难度分层"

    def test_strata_cover_all_questions(self) -> None:
        """各层题数之和必须等于 40，否则有题被漏算。"""
        for key in ("by_type", "by_difficulty"):
            total = sum(v["n"] for v in self._strat().get(key, {}).values())
            assert total == 40, f"{key} 分层题数合计 {total}，应为 40"

    def test_metric_shape(self) -> None:
        for key in ("by_type", "by_difficulty"):
            for name, v in self._strat()[key].items():
                for field in ("n", "MRR", "MRR_CI95", "Recall@10"):
                    assert field in v, f"{key}/{name} 缺少 {field}"
                lo, hi = v["MRR_CI95"]
                assert lo <= v["MRR"] <= hi, f"{key}/{name} 的 MRR 不在置信区间内"

    def test_report_has_stratified_section(self) -> None:
        text = REPORT.read_text(encoding="utf-8")
        assert "## 三·三" in text, "报告缺少分层评测小节"
        assert "按题库标注的题型与难度分层" in text

    def test_report_discloses_difficulty_label_mismatch(self) -> None:
        """难度标签与检索难度不一致这个事实必须写出来。"""
        stratified = self._strat()
        diff = stratified.get("by_difficulty") or {}
        if not ({"中", "难"} <= set(diff)):
            pytest.skip("题库缺少中/难分层，该条不适用")
        if diff["中"]["MRR"] >= diff["难"]["MRR"]:
            pytest.skip("当前数据下不存在该反常，守卫无需生效")
        text = REPORT.read_text(encoding="utf-8")
        assert "难度标签与检索难度不一致" in text, (
            "「中」档 MRR 低于「难」档，但报告没有说明原因，"
            "读者会把难度列当成检索难度的梯度"
        )
        assert "不能拿「难题也能检索到」当作能力证据" in text
