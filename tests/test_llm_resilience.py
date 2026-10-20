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
