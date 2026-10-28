"""知识库健康自检：把"看起来能跑但其实是空的"静默故障挡在测试层。

历史故障（2026-10 实测）：``PolicyVectorStore.collection_name`` 由嵌入模型哈希派生
（``carbon_policy_v5_<sha1(model)[:8]>``），而 ``_init_chroma`` 用的是
``get_or_create_collection``。因此更换嵌入模型（例如从 chromadb-default 换到
bge-small-zh）不会报错，只会**新建一个空 collection**；旧语料仍留在磁盘上
但不再被读到，政策问答从此静默返回空结果。

本地 data/chroma_db/chroma.sqlite3 实测残留 5 个 collection：
  carbon_policy_v2_3029251b  57 块   （早期只有 9 份文档的残缺库）
  carbon_policy_v3_3029251b  57 块
  carbon_policy_v4_3029251b 268 块
  carbon_policy_v5_3029251b 281 块
  carbon_policy_v5_a7d89e68 281 块   （当前生效，中文 bge）
其中 57 块那份同时也是 tests 里出现过 "展板徽标与实测块数 57 不一致" 的来源。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


@pytest.fixture()
def store_factory(tmp_path):
    """在临时目录里造 PolicyVectorStore，绝不碰仓库里的真实 chroma_db。"""
    try:
        from src.rag.vector_store import CHROMA_AVAILABLE, PolicyVectorStore
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"无法导入 vector_store：{exc}")
    if not CHROMA_AVAILABLE:  # pragma: no cover
        pytest.skip("chromadb 未安装")

    def make(embedding_model: str):
        return PolicyVectorStore(persist_dir=str(tmp_path), embedding_model=embedding_model)

    return make


def _chunk(text: str) -> dict:
    return {"text": text, "metadata": {}}


def test_empty_kb_reports_empty_status_with_ingest_hint(store_factory):
    """全新 clone 未跑 ingest：必须报 empty 并给出可执行的修复指引。"""
    vs = store_factory("chromadb-default")
    health = vs.health()

    assert health["status"] == "empty"
    assert health["count"] == 0
    assert health["documents"] == 0
    # 提示必须点名脚本，否则使用者只知道"空的"但不知道怎么修
    assert "ingest_policy_docs.py" in health["warning"]


def test_healthy_kb_reports_ok_and_no_warning(store_factory):
    """有语料时必须 ok 且不产生噪声告警。"""
    vs = store_factory("chromadb-default")
    vs.add_documents([_chunk("政策文本甲"), _chunk("政策文本乙")], "doc_a.md")

    health = vs.health()
    assert health["status"] == "ok"
    assert health["count"] == 2
    assert health["documents"] == 1
    assert health["warning"] == ""


def test_embedding_model_switch_is_detected_as_empty_with_stale_hint(store_factory):
    """核心回归：换嵌入模型会新建空 collection，必须被识别并指向旧 collection。

    这条测试复现的是真实故障路径，而不是构造出来的情形：
    collection 名 = f"carbon_policy_v5_{sha1(model)[:8]}"，所以
    embedding_model 一变，collection 名就变，get_or_create_collection 建新的空库。
    """
    legacy = store_factory("chromadb-default")
    legacy.add_documents([_chunk("旧语料一"), _chunk("旧语料二"), _chunk("旧语料三")], "old.md")
    legacy_name, legacy_count = legacy.collection_name, legacy.count()
    assert legacy_count == 3

    switched = store_factory("fastembed:BAAI/bge-small-zh-v1.5")
    assert switched.collection_name != legacy_name, "换了模型 collection 名应当不同"

    health = switched.health()
    assert health["status"] == "empty"
    assert health["count"] == 0
    # 旧 collection 必须被列出来，否则使用者无从判断"语料去哪了"
    assert health["other_collections"].get(legacy_name) == legacy_count
    # 告警必须同时点出旧 collection 与修复脚本
    assert legacy_name in health["warning"]
    assert "ingest_policy_docs.py" in health["warning"]


def test_health_lists_only_other_collections_not_self(store_factory):
    """other_collections 只装"别的" collection，不能把自己也算进去。"""
    vs = store_factory("chromadb-default")
    vs.add_documents([_chunk("政策文本")], "doc_a.md")

    health = vs.health()
    assert vs.collection_name not in health["other_collections"]


class TestHealthDoesNotPoisonChromaClient:
    """`/api/kb/health` 是只读自检，不允许改变同进程其它客户端的可用性。

    真实故障（2026-10-29，二分 tests/ 才定位）：
    历史 collection 的向量索引目录可能已被清理，只剩 sqlite 里的元数据行。
    `health()` 原先对每个历史 collection 调用 `get_collection(name).count()`，
    这会让进程内的 Chroma Rust 客户端进入坏状态——此后**同进程新建**的任何
    PolicyVectorStore 首次检索都会抛
        InternalError: Error creating hnsw segment reader: Nothing found on disk
    而 count() 仍正常返回。

    表现极具迷惑性：单独跑 `tests/test_rag_benchmark.py` 通过，先跑
    `tests/test_api.py::...::test_kb_health_endpoint_reports_structured_selfcheck`
    再跑就失败；两者代码毫无关联。

    现在 health() 只读 sqlite 元数据（`_count_collections_from_sqlite`），
    不实例化任何 collection。本文件锁住「调用 health 后新客户端仍可检索」。
    """

    def test_second_store_still_queries_after_health(self) -> None:
        from src.rag.vector_store import PolicyVectorStore

        first = PolicyVectorStore()
        if first.count() == 0:
            pytest.skip("知识库为空，跳过（需先 ingest）")

        health = first.health()
        assert health["status"] == "ok"
        assert isinstance(health["other_collections"], dict)

        # 关键断言：health() 之后新建的客户端必须还能检索
        second = PolicyVectorStore()
        hits = second.search("碳排放权交易", k=2)
        assert hits, (
            "调用 health() 后同进程新建的客户端检索返回空——"
            "很可能又对历史 collection 做了实例化"
        )

    def test_health_reports_other_collections_without_instantiating(self) -> None:
        """历史 collection 的块数应来自 sqlite 计数，而不是逐个 get_collection。"""
        from src.rag.vector_store import PolicyVectorStore

        store = PolicyVectorStore()
        if store.count() == 0:
            pytest.skip("知识库为空，跳过（需先 ingest）")
        counts = store._count_collections_from_sqlite()
        assert store.collection_name in counts, "sqlite 计数应包含当前 collection"
        assert counts[store.collection_name] == store.count(), (
            f"sqlite 计数 {counts[store.collection_name]} 与 Chroma count() "
            f"{store.count()} 不一致，说明两边口径已经分叉"
        )
