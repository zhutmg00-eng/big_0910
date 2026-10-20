"""降级与鲁棒性：ChromaDB 损坏、嵌入模型缺失、PDF 断行、增量入库。"""
from __future__ import annotations

from pathlib import Path

import pytest

import src.rag.vector_store as vs_mod
from src.rag import PolicyAdvisor, ingest_directory
from src.rag.parser import join_cjk_wrapped_lines


def _docs():
    return [{"text": "新能源重卡推广应用支持政策，鼓励物流企业使用电动重卡并建设充换电站。"},
            {"text": "柴油货车排放因子按车公里核算，满载率影响单位周转量排放。"}]


def test_chroma_init_failure_degrades_to_bm25(tmp_path, monkeypatch):
    def boom(self):
        raise RuntimeError("database disk image is malformed")
    monkeypatch.setattr(vs_mod.PolicyVectorStore, "_init_chroma", boom)
    store = vs_mod.PolicyVectorStore(persist_dir=str(tmp_path), embedding_model="none")
    stats = store.get_stats()
    assert stats["mode"] == "bm25_fallback"
    assert "初始化失败" in stats["degrade_reason"]
    store.add_documents(_docs(), "重卡政策.md")
    hits = store.search("新能源重卡支持政策", k=2)  # 默认 rrf3 自动退化为 bm25
    assert hits and hits[0]["metadata"]["source"] == "重卡政策.md"


def test_advisor_never_raises_when_search_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(vs_mod.PolicyVectorStore, "_init_chroma",
                        lambda self: (_ for _ in ()).throw(RuntimeError("x")))
    store = vs_mod.PolicyVectorStore(persist_dir=str(tmp_path), embedding_model="none")
    monkeypatch.setattr(store, "search", lambda *a, **k: (_ for _ in ()).throw(OSError("disk")))
    monkeypatch.delenv("DEEPSEEK_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    out = PolicyAdvisor(store).ask("新能源重卡有哪些政策", {})
    assert out["retrieved_sources"] == [] and isinstance(out["answer"], str)


def test_embedder_failure_skips_vector_route(tmp_path):
    pytest.importorskip("chromadb")
    store = vs_mod.PolicyVectorStore(persist_dir=str(tmp_path), embedding_model="none")
    if store.get_stats()["mode"] != "chromadb":
        pytest.skip("chromadb 不可用")

    class Fake:
        def embed_documents(self, texts):
            return [[1.0, 0.0, 0.0] for _ in texts]

    class Broken:
        def embed_query(self, q):
            raise OSError("model download failed")
    store._embedder = Fake()
    store.add_documents(_docs(), "重卡政策.md")
    store._embedder = Broken()
    assert store._rank_vector("重卡", 5) == []
    assert "嵌入模型不可用" in store.get_stats()["degrade_reason"]
    hits = store.search("新能源重卡支持政策", k=2, mode="rrf3")  # 其余两路照常工作
    assert hits and hits[0]["metadata"]["source"] == "重卡政策.md"


def test_join_cjk_wrapped_lines_fixes_pdf_breaks():
    raw = "在新能源重卡补能设施建设、绿电直连等方面先行先试，形成可复制、可推广、可\n借鉴的典型经验。\n（二十一）强化组织实施。\n推进充换电系统与车辆接口、通信协 议等关键\ue000技术标准"
    out = join_cjk_wrapped_lines(raw)
    assert "可借鉴的典型经验" in out
    assert "\n（二十一）" in out          # 新条款编号不并行
    assert "通信协议等关键技术标准" in out  # 去掉中文间空格与私用区乱码


def test_incremental_ingest_skips_unchanged(tmp_path, monkeypatch):
    monkeypatch.setattr(vs_mod, "CHROMA_AVAILABLE", False)
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "a.md").write_text("# 甲\n新能源重卡支持政策。" * 5, encoding="utf-8")
    (docs / "b.md").write_text("# 乙\n柴油货车排放因子。" * 5, encoding="utf-8")
    store = vs_mod.PolicyVectorStore(persist_dir=str(tmp_path / "db"), embedding_model="none")
    first = ingest_directory(docs, store)
    assert first["documents"] == 2 and first["skipped"] == 0
    second = ingest_directory(docs, store)
    assert second["documents"] == 0 and second["skipped"] == 2
    Path(docs / "b.md").unlink()
    third = ingest_directory(docs, store)
    assert third["removed"] == 1 and third["kb_documents"] == 1
