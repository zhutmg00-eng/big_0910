"""知识库不得收录抓取失败的错误页。

背景（真实缺陷，实测于 2026-10-29）：
`data/policy_docs/温室气体自愿减排交易管理办法_试行.md` 的正文其实是生态环境部
404 页面——整篇是「抱歉，您访问的地址有错或页面不存在」加门户导航（各省
生态环境厅列表、手机版、返回首页）。`ingest_directory` 把它当政策切成了 3 个
分块并入库，于是：

1. 检索命中的「条款」实际是网站导航文字，却会被当成政策依据展示给用户；
2. 负例集 NEG_N02 / NEG_N03 的金标 chunk 就指向这 3 个分块——即
   「判定不适用」的证据本身是错的；
3. README 与展板宣称的「40 份 / 287 块」里含这份错误页。

修复：`src/rag/__init__.py` 新增 `detect_error_page()`，命中「页面不存在」
「您访问的地址有错」等标记的文件拒绝入库并打 WARNING；两份错误页移到
`data/policy_docs_unavailable/` 保留留痕（见该目录 README）。

本文件锁三件事：语料目录里不再有错误页；入库会真的拒绝错误页（含已入库的
旧分块被清理）；负例集金标不再指向已剔除的文件。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
POLICY_DIR = ROOT / "data" / "policy_docs"
UNAVAILABLE_DIR = ROOT / "data" / "policy_docs_unavailable"
NEG_DATASET = ROOT / "docs" / "rag_benchmark" / "negative_benchmark_30_questions.json"


def _detect():
    import sys

    sys.path.insert(0, str(ROOT))
    from src.rag import detect_error_page

    return detect_error_page


class TestCorpusHasNoErrorPages:
    @pytest.mark.parametrize("path", sorted(POLICY_DIR.glob("*.md")), ids=lambda p: p.name)
    def test_every_policy_doc_is_real_text(self, path: Path) -> None:
        """语料目录里的每份文档都不能是错误页。"""
        head = path.read_text(encoding="utf-8", errors="replace")[:4000]
        marker = _detect()(head)
        assert not marker, (
            f"{path.name} 命中错误页标记「{marker}」——应移到 "
            f"data/policy_docs_unavailable/ 而不是留在语料里"
        )

    def test_unavailable_dir_keeps_the_removed_ones(self) -> None:
        """剔除的文件要有留痕，不能直接删掉（否则看不出我们试过）。"""
        names = {p.name for p in UNAVAILABLE_DIR.glob("*.md")}
        assert "温室气体自愿减排交易管理办法_试行.md" in names
        assert (UNAVAILABLE_DIR / "README.md").exists(), "缺少说明为什么剔除的 README"


class TestIngestRejectsErrorPages:
    def test_detect_error_page_hits_real_404_text(self) -> None:
        bad = (
            "中华人民共和国生态环境部\n\n抱歉，您访问的地址有错或页面不存在。\n"
            "如您是在地址栏输入网址的，请确认其拼写正确。\n"
        )
        assert _detect()(bad), "真实 404 文本未被识别"

    def test_detect_error_page_passes_short_valid_doc(self) -> None:
        """短文档不等于错误页：排放因子附件只有两百余汉字，是合法内容。"""
        ok = (
            "来源文档：2023年电力二氧化碳排放因子_附件.md\n"
            "表1 2023 年全国电力平均二氧化碳排放因子 全国 0.5306\n"
        )
        assert _detect()(ok) == ""

    def test_ingest_skips_error_page_and_removes_old_chunks(self, tmp_path) -> None:
        """入库时既要拒收新的错误页，也要清掉库里已有的同名分块。"""
        import sys

        sys.path.insert(0, str(ROOT))
        from src.rag import ingest_directory
        from src.rag.vector_store import PolicyVectorStore

        docs = tmp_path / "docs"
        docs.mkdir()
        good = docs / "真实政策.md"
        good.write_text(
            "# 真实政策\n\n**发布时间**: 2024年5月6日\n\n第一条 本文件用于测试。\n",
            encoding="utf-8",
        )
        store = PolicyVectorStore(persist_dir=str(tmp_path / "kb"))
        first = ingest_directory(docs, store)
        assert first["documents"] == 1
        before = store.count()
        assert before > 0

        # 同一个文件名被错误页覆盖（模拟抓取失败重跑）
        bad = docs / "真实政策.md"
        bad.write_text(
            "# 真实政策\n\n抱歉，您访问的地址有错或页面不存在。\n", encoding="utf-8"
        )
        second = ingest_directory(docs, store)

        assert second["documents"] == 0, "错误页被入库了"
        assert second.get("rejected"), "未在返回结果中报告被拒绝的文件"
        assert second["rejected"][0]["file"] == "真实政策.md"
        assert store.count() == 0, f"库里仍残留 {store.count()} 个错误页分块"


class TestGoldChunksDoNotPointAtRemovedFiles:
    def test_negative_gold_chunks_resolve(self) -> None:
        """负例集所有金标块必须仍在语料中（否则该题的判定依据是空的）。"""
        available = {p.name for p in POLICY_DIR.glob("*.md")}
        removed = {p.name for p in UNAVAILABLE_DIR.glob("*.md")}
        for q in json.loads(NEG_DATASET.read_text(encoding="utf-8")):
            for cid in q.get("gold_chunk_ids", []):
                src = cid.rsplit("_", 1)[0]
                assert src not in removed, (
                    f"{q['id']} 的金标块指向已剔除的错误页 {src}"
                )
                assert src in available, f"{q['id']} 的金标块来源 {src} 不在语料目录"

    def test_reanchored_questions_are_documented(self) -> None:
        """重新锚定的题必须在 notes 里写清原因，便于追溯。"""
        by_id = {
            q["id"]: q
            for q in json.loads(NEG_DATASET.read_text(encoding="utf-8"))
        }
        for qid in ("NEG_N02", "NEG_N03"):
            notes = by_id[qid].get("notes", "")
            assert "404" in notes, f"{qid} 的 notes 未说明重新锚定的原因"
