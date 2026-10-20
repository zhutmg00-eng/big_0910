"""检索指标的命名与语义必须一致——防止"循环定义指标"再次冒充拒答能力。

事故背景（评审发现，逐条本地复算确认）：

1. `scripts/evaluate_rag_benchmark.py` 的 `summarize()` 里，负例题的指标是这样算的：
       neg = [r for r in records if r["applicability_label"] == "不适用"]
       Negative_Rejection_Accuracy = sum(1 for r in neg if r["hits_at_k"][5]) / len(neg)
   也就是**"top-5 有没有命中 gold_chunk"**。命中了反而说明检索器把那条
   "其实不适用"的条款捞了出来——冠名 Rejection 却衡量命中，是循环定义。

2. 更关键的是：`src/rag/` 全目录搜不到任何拒答/弃权实现
   （`grep -r "拒答|refus|abstain" src/` 仅命中一处 UI 文案）。所以
   "合规拒答能力"根本不是检索算法提供的，它来自 LLM 提示约束层。

3. 这个指标在不同材料里被写成了 **100% / 75% / 50%** 三个值：
   - `docs/国家级优秀大创答辩逐字稿…升级版.md` 写「100% 的合规拒答率」「彻底杜绝了大模型…胡言乱语」；
   - `docs/academic_paper.md` 表 5 写 3/4 (75.0%)；
   - 而 `rag_retrieval_experiment_results.json` 的实测值是 0.5（rrf3 对 4 道负例命中 2 道）。
   同一指标三个值，且真实值最低。

本文件锁住三件事：命名如实、检索层确实没有拒答实现、对外材料不得再引用 100%/75%。
"""
import json
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
EVAL_SCRIPT = REPO_ROOT / "scripts" / "evaluate_rag_benchmark.py"
RAG_DIR = REPO_ROOT / "src" / "rag"
RESULTS = REPO_ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json"


def _read_private(rel: str) -> str:
    """私有文书（被 .gitignore 排除）缺失时跳过，而不是静默通过。"""
    p = REPO_ROOT / rel
    if not p.exists():
        pytest.skip(f"{rel} 未入库（.gitignore 排除）或不存在，跳过该口径校验")
    return p.read_text(encoding="utf-8")


class TestMetricNaming:
    """指标名必须如实反映它算的是什么。"""

    @pytest.fixture(scope="class")
    @classmethod
    def eval_source(cls):
        return EVAL_SCRIPT.read_text(encoding="utf-8")

    def test_report_uses_hitrate_name(self, eval_source):
        """必须输出 Negative_Retrieval_HitRate 这个名字。"""
        assert "Negative_Retrieval_HitRate" in eval_source

    def test_legacy_key_is_annotated_as_not_refusal(self, eval_source):
        """旧键若保留，必须带 note 说明它不是拒答率。"""
        assert "Negative_Rejection_Accuracy_note" in eval_source
        assert "不是拒答率" in eval_source or "非拒答率" in eval_source

    def test_negative_metric_has_denominator_disclosure(self, eval_source):
        """负例题只有 4 道，必须同时输出分子分母。"""
        assert "Negative_Retrieval_HitCount" in eval_source


class TestRetrievalLayerHasNoRefusalLogic:
    """检索层没有拒答实现——这是"拒答率"不能归功于算法的根本理由。"""

    def test_no_refusal_implementation_in_rag(self):
        pattern = re.compile(r"拒答|refus|abstain|弃权", re.IGNORECASE)
        offenders = []
        for py in RAG_DIR.rglob("*.py"):
            text = py.read_text(encoding="utf-8", errors="ignore")
            for m in pattern.finditer(text):
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{py.relative_to(REPO_ROOT)}:{line}")
        assert not offenders, (
            "src/rag/ 下出现了拒答相关实现，请同步更新本测试与论文中的归因说明："
            f"{offenders[:5]}"
        )


class TestMeasuredValueIsHalf:
    """实测值就是 0.5，任何材料都不得再写 100%/75%。"""

    # 撤回声明的标志词。资料里刻意保留了"早期写过 100%，已撤回"这类台账，
    # 它们不是问题；有问题的是**未加标注地继续声称**。
    RETRACT_MARKERS = ("撤回", "不成立", "已删除", "无数据支持", "非拒答", "不是", "已更正", "属循环定义")

    def test_results_json_says_half(self):
        if not RESULTS.exists():
            pytest.skip("结果文件不存在")
        data = json.loads(RESULTS.read_text(encoding="utf-8"))
        sm = data["summary_metrics"]
        # rrf3 是本文系统
        val = sm["rrf3"].get(
            "Negative_Retrieval_HitRate",
            sm["rrf3"].get("Negative_Rejection_Accuracy"),
        )
        assert val == pytest.approx(0.5), (
            f"rrf3 的负例检索命中率应为 0.5，实际 {val}。"
            "若重跑了实验导致该值变化，请同步修正论文表 5 与答辩材料。"
        )

    def _assert_no_unretracted(self, text: str, needles, rel: str):
        for line in text.splitlines():
            if not any(n in line for n in needles):
                continue
            if any(m in line for m in self.RETRACT_MARKERS):
                continue
            raise AssertionError(f"{rel} 仍有未标注撤回的断言：{line.strip()[:140]}")

    def test_paper_does_not_claim_75pct_rejection(self):
        rel = "docs/academic_paper.md"
        text = _read_private(rel)
        self._assert_no_unretracted(text, ("3/4 (75.0%)", "3/4 的正确拒答"), rel)

    def test_defense_docs_do_not_claim_100pct_rejection(self):
        docs = [
            "docs/国家级优秀大创答辩逐字稿与尖锐质询策略_升级版.md",
            "docs/大创中期答辩核心指南与评审问辨应对.md",
        ]
        for rel in docs:
            text = _read_private(rel)
            self._assert_no_unretracted(
                text,
                ("100%的合规拒答率", "100% 的合规拒答率", "100%合规拒答率",
                 "100% 合规拒答率", "负例拒答率 75%", "负例拒答 75%"),
                rel,
            )
