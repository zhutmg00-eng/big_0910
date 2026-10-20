"""Shared pytest configuration.

为什么必须有这个文件：
``src/config.py`` 在 import 时就调用 ``load_dotenv()``，把开发者本地的 ``.env``
灌进 ``os.environ``。于是本机一旦配了 ``APP_API_KEY`` / 各家 LLM key，
``src/api/main.py:87`` 的 ``API_KEY = os.getenv("APP_API_KEY", "")`` 会在
import 时读到该值，所有未带 ``X-API-Key`` 头的接口测试立刻从 200 变 401。

实测后果：只往 ``.env`` 里填了一个真实 ``DEEPSEEK_API_KEY`` 和示范用的
``APP_API_KEY``，全量测试就从 190 passed 变成 23 failed（全部是
``assert 401 == 200``）。而这些测试在 CI（没有 ``.env``）里是通过的——
也就是说"本地全绿/本地全红"取决于每个人的密钥配置，测试结果不可复现。

这里在收集任何测试模块（因而在任何 ``import src.*`` 之前）就把这些变量清空，
并把 ``load_dotenv`` 变成空操作，使 import 顺序与 CI 一致：
**测试永远运行在"无凭证"的开发模式**。

需要真实凭证的集成测试必须显式 skip（见 ``requires_llm_key``），
不允许依赖开发者本地 ``.env`` 偶然存在。
"""

from __future__ import annotations

import os

import pytest

# 任何 src.* 被 import 之前执行
_CREDENTIAL_ENV = (
    "APP_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "ZHIPU_API_KEY",
    "OPENAI_API_KEY",
)
for _name in _CREDENTIAL_ENV:
    os.environ.pop(_name, None)


@pytest.fixture(autouse=True, scope="session")
def _neutralize_dotenv_loading():
    """让 src.config 里的 load_dotenv() 失效，避免它把 .env 重新灌回来。"""
    try:
        import dotenv
    except ImportError:  # pragma: no cover - dotenv 是直接依赖
        yield
        return

    original = dotenv.load_dotenv

    def _noop(*args, **kwargs):
        return False

    dotenv.load_dotenv = _noop
    try:
        yield
    finally:
        dotenv.load_dotenv = original


def pytest_configure(config):  # noqa: ARG001 - pytest hook signature
    """更早的兜底：pytest 加载 conftest 时会先 import 部分测试模块。

    实测 m01549：只清 os.environ 不足以挡住 ``load_dotenv()``，
    必须在 conftest 被加载的瞬间就打好补丁，否则 ``src.api.main``
    可能已经在某个模块级 import 里固化了一个非空 ``API_KEY``。
    """
    for name in _CREDENTIAL_ENV:
        os.environ.pop(name, None)
    try:
        import dotenv

        if getattr(dotenv.load_dotenv, "__name__", "") != "_noop":
            dotenv.load_dotenv = lambda *a, **k: False
    except ImportError:  # pragma: no cover
        pass


def pytest_report_header(config):  # noqa: ARG001
    """在报告头里声明凭证已被清空，避免有人误判"测试跑的是生产路径"。"""
    return (
        "credentials: APP_API_KEY / LLM keys 已清空（测试运行在开发模式，"
        "需真实凭证的用 requires_llm_key 显式 skip）"
    )


def requires_llm_key(scenario: str):
    """标记需要真实 LLM 凭证的集成测试；无凭证时 skip 并说明原因。"""
    return pytest.mark.skipif(
        not os.getenv("DEEPSEEK_API_KEY") and not os.getenv("OPENAI_API_KEY"),
        reason=f"需要真实 LLM 凭证才能验证：{scenario}",
    )
