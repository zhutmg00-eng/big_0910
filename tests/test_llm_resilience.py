"""LLM 调用错误分类与响应解析。

这些测试锁定「LLM 失效时不能伪装成正常回答」这一约束：
重试要覆盖真正的瞬时错误，降级输出不得泄露内部提示词。
"""
from __future__ import annotations

import pytest

from src.rag.generator import (
    _extract_completion_text,
    _is_auth_error,
    _is_retryable_error,
    build_retrieval_answer,
    call_llm,
)


# ---- 模拟 openai SDK 的异常类型（只依赖类型名与 status_code） ----

class APITimeoutError(Exception):
    pass


class APIConnectionError(Exception):
    pass


class RateLimitError(Exception):
    pass


class InternalServerError(Exception):
    status_code = 503


class AuthenticationError(Exception):
    pass


class PermissionDeniedError(Exception):
    pass


class _Status502(Exception):
    status_code = 502


class _PlainError(Exception):
    pass


@pytest.mark.parametrize("exc", [
    APITimeoutError("Request timed out."),
    APIConnectionError("Connection reset by peer"),
    RateLimitError("too many requests"),
    InternalServerError("model busy"),
    _Status502("bad gateway"),
])
def test_transient_errors_are_retryable(exc):
    assert _is_retryable_error(exc) is True
    assert _is_auth_error(exc) is False


@pytest.mark.parametrize("exc", [
    AuthenticationError("Invalid API key"),
    PermissionDeniedError("forbidden"),
])
def test_auth_errors_are_not_retried(exc):
    assert _is_auth_error(exc) is True


def test_unknown_error_is_neither_retried_nor_auth():
    exc = _PlainError("something odd happened")
    assert _is_retryable_error(exc) is False
    assert _is_auth_error(exc) is False


# ---- 响应解析 ----

class _Msg:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content, finish_reason="stop"):
        self.message = _Msg(content)
        self.finish_reason = finish_reason


class _Resp:
    def __init__(self, choices):
        self.choices = choices


def test_extract_returns_content():
    assert _extract_completion_text(_Resp([_Choice("  hello  ")])) == "hello"


def test_extract_marks_truncated_answer():
    text = _extract_completion_text(_Resp([_Choice("partial", "length")]))
    assert text.startswith("partial")
    assert "截断" in text


def test_extract_rejects_empty_content():
    with pytest.raises(RuntimeError, match="空内容"):
        _extract_completion_text(_Resp([_Choice(None)]))


def test_extract_rejects_empty_choices():
    with pytest.raises(RuntimeError, match="空 choices"):
        _extract_completion_text(_Resp([]))


# ---- call_llm 降级路径不得泄露提示词 ----

def test_call_llm_without_api_key_returns_fallback(monkeypatch):
    import src.rag.generator as gen

    monkeypatch.setattr(gen, "get_llm_config", lambda model: {"api_key": "", "base_url": "x", "model": "m"})
    out = call_llm("sys", "user", fallback_answer="检索摘录内容")
    assert "检索摘录内容" in out


def test_call_llm_failure_does_not_echo_user_prompt(monkeypatch):
    """降级输出绝不能把内部提示词模板当回答返回。"""
    import src.rag.generator as gen

    monkeypatch.setattr(
        gen, "get_llm_config",
        lambda model: {"api_key": "fake", "base_url": "http://127.0.0.1:1", "model": "m"},
    )
    secret_prompt = "====== 内部模板 ======\n[参考条款1] 来源: 机密政策全文"

    class _BoomClient:
        def __init__(self, **kwargs):
            self.chat = self
            self.completions = self

        def create(self, **kwargs):
            raise _PlainError("unexpected")

    import openai
    monkeypatch.setattr(openai, "OpenAI", _BoomClient)

    out = call_llm("sys", secret_prompt, fallback_answer=None)
    assert "LLM 调用失败" in out
    assert "内部模板" not in out
    assert "参考条款1" not in out

class TestApplicabilityNoteIsNotAConstantTail:
    """第 11 轮评审实测：5 个互不相关的问题，答案尾部的【适用性提示】逐字相同。

    那段提示原先无条件拼在每条检索式回答末尾，等于把一句与检索内容无关的模板
    当成检索结论的一部分。现在改成只在命中「其他行业履约规定」时才出现。
    """

    @staticmethod
    def _chunk(source: str, text: str = "示例正文") -> dict:
        return {"text": text, "metadata": {"source": source, "date": ""}}

    def test_note_absent_for_unrelated_documents(self):
        answer = build_retrieval_answer(
            "新能源重卡购置补贴还能申请吗",
            [self._chunk("推动新能源重卡规模化应用实施方案_2026.md")],
        )
        assert "适用性提示" not in answer

    def test_note_present_when_hitting_other_industry_rules(self):
        answer = build_retrieval_answer(
            "物流企业是否纳入全国碳市场",
            [self._chunk("企业温室气体排放核算与报告指南_发电设施.md")],
        )
        assert "适用性提示" in answer
        assert "未纳入全国碳市场配额管理" in answer

    def test_tail_is_not_identical_across_unrelated_questions(self):
        unrelated = [
            ("新能源重卡购置补贴还能申请吗", "推动新能源重卡规模化应用实施方案_2026.md"),
            ("物流园区光伏算不算减排", "温室气体自愿减排交易管理办法_试行.md"),
        ]
        tails = {build_retrieval_answer(q, [self._chunk(src)])[-80:] for q, src in unrelated}
        assert len(tails) == len(unrelated), "不同问题不应共享同一段模板尾巴"
