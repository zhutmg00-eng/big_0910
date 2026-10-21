"""历史 collection 清理必须安全。

换嵌入模型会派生新的 collection 名（``carbon_policy_v5_<hash>``），旧语料
留在同一 sqlite 里但不再被读到。``prune_stale_collections`` 是删除操作，
因此测试要锁定三件事：
1. 默认 dry_run 不删任何东西；
2. 只会删「不是当前 collection」的那些，绝不动当前库；
3. 当前库为空时脚本拒绝执行（否则清完可能一份语料都不剩）。
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.rag.vector_store import PolicyVectorStore

REPO_ROOT = Path(__file__).resolve().parent.parent


def _seed_store(tmp_path: Path, collection_dir_name: str) -> PolicyVectorStore:
    """在临时目录建一份小库（绝不碰真实 data/chroma_db）。"""
    store = PolicyVectorStore(persist_dir=str(tmp_path))
    store.add_documents(
        chunks=[{"text": "重型柴油货车排放因子为 0.877 kgCO2/km",
                 "metadata": {"source": "测试文件A.md", "chunk_index": 0}}],
        doc_source="测试文件A.md",
    )
    assert store.count() > 0
    return store


class TestPruneStaleCollections:
    def test_dry_run_deletes_nothing(self, tmp_path):
        store = _seed_store(tmp_path, "v5")
        live_name = store.collection_name

        # 造一份「历史」collection：换个嵌入模型名重新打开同一目录
        old = PolicyVectorStore(persist_dir=str(tmp_path),
                                embedding_model="chromadb-default")
        old.add_documents(
            chunks=[{"text": "旧语料", "metadata": {"source": "旧文件.md", "chunk_index": 0}}],
            doc_source="旧文件.md",
        )
        assert old.collection_name != live_name

        plan = store.prune_stale_collections(dry_run=True)
        assert plan["dry_run"] is True
        assert old.collection_name in plan["removed"]
        # 什么都没删
        assert PolicyVectorStore(persist_dir=str(tmp_path),
                                 embedding_model="chromadb-default").count() > 0

    def test_apply_keeps_current_collection_intact(self, tmp_path):
        store = _seed_store(tmp_path, "v5")
        live_name = store.collection_name
        live_count = store.count()

        old = PolicyVectorStore(persist_dir=str(tmp_path),
                                embedding_model="chromadb-default")
        old.add_documents(
            chunks=[{"text": "旧语料", "metadata": {"source": "旧文件.md", "chunk_index": 0}}],
            doc_source="旧文件.md",
        )

        plan = store.prune_stale_collections(dry_run=False)
        assert old.collection_name in plan["removed"]
        assert live_name == plan["kept"]

        # 当前库必须原样还在，块数不变
        again = PolicyVectorStore(persist_dir=str(tmp_path))
        assert again.collection_name == live_name
        assert again.count() == live_count
        # 历史 collection 已经不在了
        health = again.health()
        assert old.collection_name not in health["other_collections"]

    def test_no_stale_means_empty_plan(self, tmp_path):
        store = _seed_store(tmp_path, "v5")
        plan = store.prune_stale_collections(dry_run=False)
        assert plan["removed"] == {}


class TestPruneScriptRefusesOnEmptyKb:
    def _run(self, *args: str, cwd: Path) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(
            [sys.executable, str(REPO_ROOT / "scripts" / "prune_kb_collections.py"), *args],
            cwd=str(cwd), capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
            env=env,
        )

    def test_refuses_when_current_collection_empty(self, tmp_path):
        # 空目录 -> 当前 collection 0 块 -> 脚本必须中止且返回非 0
        res = self._run("--persist-dir", str(tmp_path), cwd=tmp_path)
        assert res.returncode != 0, f"空库时不应放行清理：{res.stdout}"
        assert "ingest_policy_docs.py" in res.stdout
        assert "已中止" in res.stdout

    def test_preview_by_default(self, tmp_path):
        _seed_store(tmp_path, "v5")
        old = PolicyVectorStore(persist_dir=str(tmp_path), embedding_model="chromadb-default")
        old.add_documents(
            chunks=[{"text": "旧语料", "metadata": {"source": "旧文件.md", "chunk_index": 0}}],
            doc_source="旧文件.md",
        )
        res = self._run("--persist-dir", str(tmp_path), cwd=tmp_path)
        assert res.returncode == 0, res.stderr
        assert "仅为预览" in res.stdout
        assert old.collection_name in res.stdout
        # 预览不删除
        assert PolicyVectorStore(persist_dir=str(tmp_path),
                                 embedding_model="chromadb-default").count() > 0

    @pytest.mark.parametrize("flag", ["--apply"])
    def test_apply_removes_and_reports(self, tmp_path, flag):
        store = _seed_store(tmp_path, "v5")
        live_count = store.count()
        old = PolicyVectorStore(persist_dir=str(tmp_path), embedding_model="chromadb-default")
        old.add_documents(
            chunks=[{"text": "旧语料", "metadata": {"source": "旧文件.md", "chunk_index": 0}}],
            doc_source="旧文件.md",
        )
        res = self._run("--persist-dir", str(tmp_path), flag, cwd=tmp_path)
        assert res.returncode == 0, f"{res.stdout}\n{res.stderr}"
        assert "已删除" in res.stdout
        again = PolicyVectorStore(persist_dir=str(tmp_path))
        assert again.count() == live_count

