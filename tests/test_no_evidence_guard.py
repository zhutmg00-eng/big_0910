"""空证据守卫：知识库为空时不得让大模型自由作答。

背景（真实缺陷，实测于 2026-10）：
本想在空知识库上验证"干净 clone 后政策问答为空"的降级体验，用临时空目录造
PolicyVectorStore 后调 PolicyAdvisor().ask(...)，得到 retrieved_sources 为 0 条，
但 answer 依然由大模型生成，内容是"未检索到任何相关政策条款"，
紧接着又断言"全国碳市场目前仅覆盖发电、钢铁、水泥、电解铝等重点排放行业，
物流运输行业未被纳入配额管理范围"——该句没有任何检索证据支撑，
而检索层与日志都不报错。

对一个以"每条结论可溯源到政策原文"为卖点的政策问答，这比直接报错危险得多：
用户看到的是通顺、专业、带政策口吻的答案，无从判断它来自语料还是模型先验。

修复后：证据为 0 时短路，不调用大模型，返回显式说明 + evidence_warning。
本文件锁死该行为，防止有人为了"体验流畅"把空证据分支去掉。
"""

from __future__ import annotations

import pytest

from src.models.policy import PolicyAnswer
from src.rag import PolicyAdvisor
from src.rag.vector_store import PolicyVectorStore


@pytest.fixture
def empty_store(tmp_path):
    """指向空目录的向量库：count 为 0，检索必然返回空列表。"""
    store = PolicyVectorStore(persist_dir=str(tmp_path / "kb_empty"))
    assert store.count() == 0, "空目录应当得到空库"
    return store


def test_empty_kb_does_not_call_llm(empty_store, monkeypatch) -> None:
    """空证据时必须短路：llm 一旦被调用，就说明防线失守。"""
    import src.rag as rag_pkg

    def _boom(*args, **kwargs):
        raise AssertionError(
            "空证据时不应调用大模型——没有证据的作答等同于编造政策依据"
        )

    monkeypatch.setattr(rag_pkg, "call_llm", _boom)

    result = PolicyAdvisor(vector_store=empty_store).ask(
        "物流企业现在需要缴纳碳配额吗？", {"企业名称": "测试物流"}
    )

    assert result["retrieved_sources"] == []
    assert result["evidence_count"] == 0
    assert result["answer"].strip(), "短路也要给出可读说明，不能返回空字符串"


def test_empty_kb_answer_states_no_evidence(empty_store) -> None:
    """说明文本必须自陈「没找到」，并给用户可执行的下一步。

    第 8 轮评审 P1-1 指出原实现把 `python scripts/ingest_policy_docs.py
    --force`、`GET /api/kb/health` 这些开发者命令当成给车队老板的答复。
    现在主体改成「换说法 / 换主题 / 找管理员」，运维命令退到
    evidence_warning 的括注里。
    """
    result = PolicyAdvisor(vector_store=empty_store).ask("碳排放怎么核算？", {})
    answer = result["answer"]

    assert "没有找到可引用的条款" in answer
    assert "不作答" in answer
    # 必须给出下一步动作，而不是让用户卡在这里
    assert "换个说法" in answer
    assert "系统管理员" in answer
    assert result["evidence_warning"], "evidence_warning 不能为空，前端据此显示告警"
    assert "未生成回答" in result["evidence_warning"]
    # 运维信息仍在，但只出现在告警的括注里，不占答复主体
    assert "ingest_policy_docs.py" in result["evidence_warning"]
    assert "/api/kb/health" in result["evidence_warning"]
    assert "ingest_policy_docs.py" not in answer


def test_empty_kb_answer_does_not_assert_policy_facts(empty_store) -> None:
    """回归锁：不得复现"先说没检索到、再断言行业范围"的自相矛盾输出。"""
    answer = PolicyAdvisor(vector_store=empty_store).ask(
        "物流企业现在需要缴纳碳配额吗？", {}
    )["answer"]

    for forbidden in ("电解铝", "钢铁、水泥", "未被纳入配额管理范围"):
        assert forbidden not in answer, (
            f"空证据时出现了无出处的政策事实断言：{forbidden}"
        )


def test_evidence_fields_present_on_normal_path() -> None:
    """有证据分支也要带 evidence_count，且与 sources 长度一致（不依赖真实库）。"""
    fake_sources = [
        {"source": "某政策.md", "date": "2026-01-01", "relevance": 0.9,
         "chunk_id": "c1", "excerpt": "摘录", "retrievers": ["bm25"]}
    ]
    payload = PolicyAnswer(
        question="q",
        retrieved_sources=fake_sources,
        answer="a",
        evidence_count=len(fake_sources),
    )
    assert payload.evidence_count == 1
    assert payload.evidence_warning == ""


def test_nonexistent_question_still_returns_structure(empty_store) -> None:
    """空库下返回结构必须完整，避免下游 .get 抛 KeyError。"""
    result = PolicyAdvisor(vector_store=empty_store).ask("完全不相关的问题 xyzzzy", {})
    for key in ("question", "retrieved_sources", "answer", "evidence_count", "evidence_warning"):
        assert key in result, f"返回结构缺少字段 {key}"


class _StubStore:
    """返回固定相关性证据的向量库替身，用于验证低相关度提示。

    必须带 ``mode`` 与 ``rank``：第 10 轮评审发现融合检索下 ``1 - distance``
    是 RRF 名次分位而不是相关度，所以 ``_result_relevance`` 只在 vector /
    keyword 模式下把它当相关度用。替身默认模拟 vector 模式。
    """

    def __init__(self, relevance: float, n: int = 5, mode: str = "vector",
                 retrievers=("vector",)):
        self.relevance = relevance
        self.n = n
        self.mode = mode
        self.retrievers = list(retrievers)

    def search(self, query, k=5):  # noqa: ARG002 - 接口签名对齐
        return [
            {
                "id": f"c{i}",
                "text": "来源文档：x.md\n正文",
                "distance": 1 - self.relevance,
                "score": self.relevance,
                "metadata": {"source": "某政策.md", "date": "2026-01-01"},
                "retrievers": list(self.retrievers),
                "rank": i + 1,
            }
            for i in range(self.n)
        ]

    def search_mode(self) -> str:
        return self.mode


class TestLowRelevanceWarning:
    """第 9 轮评审 P1：POST /api/ask {"question":"?"} 返回 5 条证据但相关性
    只有 0.501–0.533，evidence_warning 却是空的。

    稠密向量对任何输入都会给出 0.5 左右的余弦相似度，所以「检索到了」不等于
    「对题」；不提示的话用户会看到一段以错位条款为依据、语气却很确定的答复。
    """

    def test_low_relevance_emits_warning(self, monkeypatch) -> None:
        monkeypatch.setattr("src.rag.call_llm", lambda *a, **k: "答复")
        result = PolicyAdvisor(vector_store=_StubStore(0.52)).ask("?", {})
        assert result["evidence_count"] == 5
        warning = result["evidence_warning"]
        assert warning, "低相关度时不能静默"
        assert "0.52" in warning
        assert "可能并不对题" in warning

    def test_high_relevance_has_no_warning(self, monkeypatch) -> None:
        monkeypatch.setattr("src.rag.call_llm", lambda *a, **k: "答复")
        result = PolicyAdvisor(vector_store=_StubStore(0.88)).ask("物流企业是否纳入碳市场？", {})
        assert result["evidence_warning"] == ""

    def test_threshold_is_configurable_and_used(self, monkeypatch) -> None:
        monkeypatch.setattr("src.rag.RETRIEVAL_THRESHOLD", 0.90)
        monkeypatch.setattr("src.rag.call_llm", lambda *a, **k: "答复")
        result = PolicyAdvisor(vector_store=_StubStore(0.88)).ask("q", {})
        assert result["evidence_warning"], "阈值调到 0.90 后 0.88 应触发提示"
        assert "0.90" in result["evidence_warning"]

class TestFusedRelevanceIsNotCorrelation:
    """第 10 轮评审实测的口径错误：融合检索里 1-distance 是 RRF 名次分位。

    现象：rrf3 下被三路同时排第一的「配额清缴期限」relevance ≈ 0.00，
    完全对题却被报成「最高相关性只有 0.00，可能并不对题」；而「我想请假」
    的 relevance = 0.994，比真正对题的问题还高。这里锁住修复后的语义。
    """

    def _sources(self, *retrievers_lists, threshold=0.62):
        from src.rag import _low_relevance_warning

        sources = [
            {"relevance": 1.0 if len(r) >= 2 else 0.0,
             "relevance_basis": "multi_retriever_agreement" if len(r) >= 2 else "single_retriever_hit",
             "relevance_mode": "rrf3", "retrievers": list(r), "rank": i + 1}
            for i, r in enumerate(retrievers_lists)
        ]
        return _low_relevance_warning(sources)

    def test_perfect_hit_is_not_reported_as_low_relevance(self, monkeypatch) -> None:
        monkeypatch.setattr("src.rag.call_llm", lambda *a, **k: "答复")
        store = _StubStore(0.0, n=3, mode="rrf3", retrievers=("bm25", "vector", "keyword"))
        result = PolicyAdvisor(vector_store=store).ask("配额清缴期限", {})
        # distance = 1 - 0.0 = 1.0（旧口径会算成 relevance 0.0）
        assert result["evidence_warning"] == ""

    def test_fused_mode_never_claims_a_correlation_number(self, monkeypatch) -> None:
        monkeypatch.setattr("src.rag.call_llm", lambda *a, **k: "答复")
        store = _StubStore(0.99, n=3, mode="rrf3", retrievers=("bm25", "vector"))
        result = PolicyAdvisor(vector_store=store).ask("q", {})
        assert result["retrieved_sources"][0]["relevance"] == 1.0
        assert result["retrieved_sources"][0]["relevance_basis"] == "multi_retriever_agreement"

    def test_single_retriever_hit_is_flagged(self) -> None:
        warning = self._sources(("bm25",), ("bm25",), ("bm25",))
        assert "没有一条被两个以上检索器共同召回" in warning

    def test_partial_support_is_flagged(self) -> None:
        warning = self._sources(("bm25", "vector"), ("bm25",), ("bm25",), ("keyword",), ("bm25",))
        assert "只有 1 条被两个以上检索器共同召回" in warning

    def test_full_support_is_silent(self) -> None:
        assert self._sources(("bm25", "vector"), ("bm25", "keyword")) == ""
