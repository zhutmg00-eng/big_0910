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
    """说明文本必须自陈"没有证据"，并给出可操作的排查路径。"""
    result = PolicyAdvisor(vector_store=empty_store).ask("碳排放怎么核算？", {})
    answer = result["answer"]

    assert "未在知识库中检索到" in answer
    assert "不生成回答" in answer
    # 必须给出下一步动作，而不是让用户卡在这里
    assert "ingest_policy_docs.py" in answer
    assert "/api/kb/health" in answer
    assert result["evidence_warning"], "evidence_warning 不能为空，前端据此显示告警"
    assert "未调用大模型" in result["evidence_warning"]


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
