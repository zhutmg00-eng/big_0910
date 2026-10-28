"""引用可溯源检查器必须能识破伪造引用，否则它只是一个永远返回 100% 的空壳。

背景（2026-10-27，I-6）：
RQ2 此前只评检索（MRR/Recall），没有任何指标检验**回答本身**是否落在
检索到的条款上——而「每条结论可溯源」正是项目对外的核心卖点。

`scripts/evaluate_answer_grounding.py` 在未配置 LLM 的路径上（回答由逐字
摘录生成）会得到 100%：这是**按构造成立**的，不是发现。它的价值有两层：
1. 回归锁：若有人为了「读起来更顺」把摘录改成转述，指标会掉，测试报警；
2. 检查器可用：配置 LLM 后同一脚本可直接评测真实生成结果。

因此本文件的重点是**负例对照**：故意注入伪造文件名、伪造数值、跨行假引用，
检查器必须逐一点名。只断言「真实结果等于 100%」而不验证检查器能报错，
等于没测。
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "evaluate_answer_grounding.py"
RESULTS = ROOT / "docs" / "rag_benchmark" / "answer_grounding_results.json"


def _mod():
    spec = importlib.util.spec_from_file_location("evaluate_answer_grounding", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CHUNKS = [
    {
        "id": "a_0",
        "text": "来源文档：A.md 全国碳市场覆盖发电行业，2023 年度配额总量为 51.2 亿吨。"
                "重点排放单位年度排放量达到 2.6 万吨二氧化碳当量。",
        "metadata": {"source": "A.md"},
    },
    {
        "id": "b_0",
        "text": "来源文档：B.md 物流运输行业目前未纳入全国碳市场配额管理。",
        "metadata": {"source": "B.md"},
    },
]


class TestNegativeControls:
    """检查器必须能报错——这是它唯一的用处。"""

    def test_fabricated_citation_is_caught(self):
        mod = _mod()
        answer = "【政策依据】《C.md》规定运输企业须按 5% 履约。"
        result = mod.check_answer(answer, CHUNKS)
        assert result["ungrounded_citations"] == ["C.md"], (
            "伪造的文件名没有被拦下，检查器形同虚设"
        )
        assert result["citations_grounded"] == 0

    def test_fabricated_number_is_caught(self):
        mod = _mod()
        answer = "【政策依据】《A.md》规定配额总量为 88.8 亿吨。"
        result = mod.check_answer(answer, CHUNKS)
        assert "88.8亿吨" in result["ungrounded_numbers"], (
            f"伪造数值没有被拦下：{result['ungrounded_numbers']}"
        )

    def test_grounded_answer_passes(self):
        """真实存在的文件与数值必须放行，否则检查器会满屏误报。"""
        mod = _mod()
        answer = "【政策依据】《A.md》规定 2023 年度配额总量为 51.2 亿吨；《B.md》说明行业未纳管。"
        result = mod.check_answer(answer, CHUNKS)
        assert result["ungrounded_citations"] == []
        assert result["ungrounded_numbers"] == []
        assert result["citations"] == 2

    def test_crossline_citation_is_not_parsed_as_one_name(self):
        """证据原文里跨行的《…》不得被拼成一个假文件名（实测 Q02 踩过）。"""
        mod = _mod()
        answer = (
            "- 《2026 年度碳\n"
            "- 《2025-2026年度配额总量和分配方案_征求意见稿.md》（2026）：正文"
        )
        got = mod.extract_citations(answer)
        assert got == ["2025-2026年度配额总量和分配方案_征求意见稿.md"], (
            f"跨行文本被解析成假文件名：{got}"
        )

    def test_echoed_question_is_not_checked(self):
        """回显的用户问题不算系统断言（实测 Q33：「运距约700公里」被判编造）。"""
        mod = _mod()
        answer = "针对“运距约700公里的大宗货物运输有何导向？”，当前最相关的资料是《A.md》。"
        result = mod.check_answer(answer, CHUNKS)
        assert result["ungrounded_numbers"] == [], (
            f"回显问题里的数值被误判为编造：{result['ungrounded_numbers']}"
        )

    def test_thousands_separator_is_grounded(self):
        """原文写 51.2 亿、回答写 512,000 万元这类数值换算不在范围内，
        但千分位写法必须认（原文 2,600 与回答 2600 视为同一数值）。"""
        mod = _mod()
        chunks = [{"id": "c", "text": "排放量 2,600 吨。", "metadata": {"source": "C.md"}}]
        result = mod.check_answer("《C.md》称排放量 2600 吨。", chunks)
        assert result["ungrounded_numbers"] == []


class TestCommittedResults:
    @pytest.fixture(scope="class")
    @classmethod
    def payload(cls):
        if not RESULTS.exists():
            pytest.skip("尚未运行 scripts/evaluate_answer_grounding.py")
        return json.loads(RESULTS.read_text(encoding="utf-8"))

    def test_declares_metric_scope(self, payload):
        """必须自陈这是可溯源性、不是忠实度，并说明 100% 的成因。"""
        note = payload["note"]
        assert "不是「忠实度」" in note
        assert "按构造成立" in note
        assert "回归锁" in note

    def test_scores_are_full_on_excerpt_path(self, payload):
        """摘录路径下必须满分；掉下来说明有人把摘录改成了转述。"""
        s = payload["summary"]
        assert s["citation_grounding_rate"] == 1.0, (
            f"引用文件名可溯源率 {s['citation_grounding_rate']}，"
            f"未溯源：{s['citations_grounded']}/{s['citations_total']}"
        )
        assert s["number_grounding_rate"] == 1.0, (
            f"数值可溯源率 {s['number_grounding_rate']}，"
            f"未溯源：{s['numbers_grounded']}/{s['numbers_total']}"
        )

    def test_covers_all_gold_questions(self, payload):
        gold = json.loads(
            (ROOT / "docs" / "rag_benchmark" / "rag_benchmark_gold_dataset.json")
            .read_text(encoding="utf-8")
        )
        assert payload["design"]["n_questions"] == len(gold)
        assert {q["id"] for q in payload["per_question"]} == {q["id"] for q in gold}

    def test_has_nonzero_denominators(self, payload):
        """分母为 0 时 _rate 会返回 1.0，看起来满分实际什么都没测。"""
        s = payload["summary"]
        assert s["citations_total"] > 0
        assert s["numbers_total"] > 0
