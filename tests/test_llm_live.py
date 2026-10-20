"""真实 LLM 全链路集成测试（需要真实凭证，CI 中自动 skip）。

与 ``tests/test_llm_resilience.py`` 的分工：
- 那个文件用 mock 验证**错误分类与响应解析**的代码分支，不需要网络；
- 本文件用真实 DeepSeek key 验证**真实 API 的行为假设**，因为 mock 测不出
  "SDK 到底抛哪个异常类""真实响应长什么样""重试实际耗时多久"。

这些假设一旦漂移（SDK 改异常层次、网关改状态码、模型改名），mock 测试仍会
全绿，但线上已经退化成"每次都返回检索摘录"。所以必须有真跑的一层。

凭证来源：``tests/conftest.py`` 会把 ``.env`` 的凭证清空以保证单元测试可复现，
因此本文件显式从 ``.env`` 读取而非依赖 ``os.environ``，并在读不到时 skip。
绝不在代码或输出里打印 key 明文。
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parents[1]


def _real_key(name: str) -> str:
    """只从 .env 取真实 key（conftest 已清空 os.environ）。"""
    try:
        from dotenv import dotenv_values
    except ImportError:  # pragma: no cover
        return ""
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return ""
    value = (dotenv_values(env_file).get(name) or "").strip()
    # .env.example 的占位值不算凭证
    if not value or value in {"your-api-key-here", "sk-xxx", "changeme"}:
        return ""
    return value


DEEPSEEK_KEY = _real_key("DEEPSEEK_API_KEY")

requires_live_llm = pytest.mark.skipif(
    not DEEPSEEK_KEY,
    reason="需要 .env 中配置真实 DEEPSEEK_API_KEY 才能验证真实 API 行为",
)


@pytest.fixture
def live_config(monkeypatch):
    """把真实 key 只注入到被测代码读取的位置，不写 os.environ 全局。"""
    import src.rag.generator as generator

    original = generator.get_llm_config

    def _patched(model=None):
        cfg = dict(original(model))
        cfg["api_key"] = DEEPSEEK_KEY
        return cfg

    monkeypatch.setattr(generator, "get_llm_config", _patched)
    return None


@requires_live_llm
def test_live_call_llm_returns_real_completion(live_config) -> None:
    """真实调用：必须拿到非空、与问题相关的回答，而不是降级提示。"""
    from src.rag.generator import call_llm

    out = call_llm("你是一个简洁的助手，用一句话回答。", "什么是碳配额？", fallback_answer="FALLBACK")

    assert out.strip(), "真实调用不应返回空字符串"
    assert "FALLBACK" not in out, "真实调用不应落到 fallback 分支"
    assert "LLM 调用失败" not in out, f"真实调用失败：{out[:120]}"
    assert any(kw in out for kw in ("排放", "配额", "碳")), (
        f"回答与问题不相关，疑似网关返回了别的内容：{out[:160]}"
    )


@requires_live_llm
def test_live_advisory_cites_real_policy_documents(live_config) -> None:
    """端到端：真实检索 + 真实生成，回答必须引用知识库里真实存在的文件。"""
    pytest.importorskip("chromadb")
    from src.rag import PolicyAdvisor
    from src.rag.vector_store import get_vector_store

    store = get_vector_store()
    if store.count() <= 0:
        pytest.skip("知识库为空（未执行 scripts/ingest_policy_docs.py），跳过端到端验证")

    index = store.source_hashes() if hasattr(store, "source_hashes") else {}
    result = PolicyAdvisor(vector_store=store).ask(
        "新能源重卡推广应用有哪些支持政策？", {"企业名称": "测试物流企业"}
    )

    assert result["evidence_count"] > 0, "真实知识库不应检索出 0 条证据"
    assert result["evidence_warning"] == ""
    # 每条来源都必须是知识库里真实存在的文件名，而不是模型编的书名
    known = set(index.keys()) if isinstance(index, dict) else set()
    for src in result["retrieved_sources"]:
        if known:
            assert src["source"] in known, f"来源 {src['source']} 不在知识库索引中"
    assert any(kw in result["answer"] for kw in ("政策", "重卡", "新能源")), (
        f"回答未涉及问题主题：{result['answer'][:160]}"
    )


@requires_live_llm
def test_live_auth_error_is_not_retried(live_config, monkeypatch) -> None:
    """真实 SDK 的鉴权异常必须被识破，且不重试、不泄漏 key。"""
    import src.rag.generator as generator

    monkeypatch.setattr(
        generator, "get_llm_config", lambda model=None: {
            "api_key": "sk-" + "0" * 32,
            "base_url": "https://api.deepseek.com",
            "model": "deepseek-chat",
        }
    )

    out = generator.call_llm("你是助手", "说一句话", fallback_answer="FALLBACK_SENTINEL")

    assert "认证失败" in out, f"鉴权错误未被识别：{out[:160]}"
    assert "FALLBACK_SENTINEL" not in out, "鉴权失败不应降级成检索摘录——凭证问题必须显式报出"
    assert "0" * 32 not in out, "错误信息中泄漏了 key"
