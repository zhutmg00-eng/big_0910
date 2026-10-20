"""测试环境的凭证隔离：测试结果不得依赖开发者本地 .env。

背景（真实缺陷，实测于 2026-10）：
为了用真实 key 做端到端联调，往 .env 里填了 ``DEEPSEEK_API_KEY`` 和示范用的
``APP_API_KEY``（来自 .env.example 的 your-api-key-here）。结果全量测试从
190 passed 变成 23 failed，失败项清一色是 ``assert 401 == 200``。

根因链：
1. ``src/config.py:5-6`` 在 import 时就执行 ``load_dotenv()``（不带 override）；
2. ``src/api/main.py:87`` 在 import 时执行 ``API_KEY = os.getenv("APP_API_KEY", "")``，
   把值固化进模块常量；
3. 于是只要 .env 里有 APP_API_KEY，所有不带 ``X-API-Key`` 头的接口测试全变 401。

危害不是"测试红了"，而是**测试结果不可复现**：同一份代码，CI（无 .env）全绿、
开发者本机（有 .env）全红，无法判断到底哪边是真实缺陷。

修复：``tests/conftest.py`` 在 pytest 加载阶段清空 5 个凭证变量并禁用
``load_dotenv``，使测试恒定运行在"无凭证的开发模式"，与 CI 一致。
本文件锁死该前提，防止有人把 conftest 里的隔离删掉或改坏。
"""

from __future__ import annotations

import os

CREDENTIAL_ENV = (
    "APP_API_KEY",
    "DEEPSEEK_API_KEY",
    "DASHSCOPE_API_KEY",
    "ZHIPU_API_KEY",
    "OPENAI_API_KEY",
)


def test_credential_env_vars_are_cleared() -> None:
    leaked = {name: os.getenv(name) for name in CREDENTIAL_ENV if os.getenv(name)}
    assert not leaked, (
        f"测试环境下这些凭证变量应为空，实际非空：{sorted(leaked)}。"
        "若 .env 里配了 key，接口测试会全部 401——请在 tests/conftest.py 隔离。"
    )


def test_api_module_key_constant_is_empty() -> None:
    """main.API_KEY 是 import 时固化的常量，必须为空才能走开发模式。"""
    from src.api import main

    assert main.API_KEY == "", (
        f"src.api.main.API_KEY 应为空字符串（开发模式），实际为 {main.API_KEY!r}；"
        "说明 .env 在 import 前被加载且未被测试隔离"
    )


def test_dotenv_loader_is_disabled() -> None:
    """load_dotenv 必须被替换掉，否则任何后续 import 都会把 .env 灌回来。"""
    import dotenv

    assert dotenv.load_dotenv(".env") is False, (
        "load_dotenv 在测试中应恒返回 False（未加载任何文件）"
    )
    for name in CREDENTIAL_ENV:
        assert os.getenv(name) is None, f"{name} 被 load_dotenv 重新灌入"


def test_unauthenticated_endpoint_succeeds() -> None:
    """端到端确认：不带 X-API-Key 也能访问，即开发模式生效。"""
    from fastapi.testclient import TestClient

    from src.api.main import app

    client = TestClient(app)
    assert client.get("/api/health").status_code == 200
    assert client.get("/api/vehicle-types").status_code == 200
