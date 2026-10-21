"""RAG模块测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.rag.generator import build_retrieval_answer
from src.rag.parser import clean_policy_text, chunk_policy_text, parse_document
from src.rag.vector_store import _lexical_relevance


class TestParser:
    def test_clean_removes_empty_lines(self):
        """清洗应移除空行"""
        raw = "第一行\n\n\n第二行\n\n第三行"
        cleaned = clean_policy_text(raw)
        assert "\n\n" not in cleaned

    def test_parse_markdown_and_remove_web_footer_noise(self, tmp_path):
        markdown = tmp_path / "policy.md"
        markdown.write_text(
            "# 交通运输碳达峰方案\n\n正文规定运输结构优化。\n"
            "**URL**: https://example.com/policy\n版权所有：中国政府网\n"
            "京ICP备05070218号\n网站标识码bm01000001\n",
            encoding="utf-8",
        )
        raw = parse_document(markdown)
        cleaned = clean_policy_text(raw)
        assert "交通运输碳达峰方案" in cleaned
        assert "运输结构优化" in cleaned
        assert "版权所有" not in cleaned
        assert "ICP备" not in cleaned
        assert "网站标识码" not in cleaned
        assert "example.com" not in cleaned

    def test_clean_deduplicates_repeated_long_lines(self):
        line = "这是一条被网页抓取结果重复保存的较长政策正文内容。"
        cleaned = clean_policy_text(f"{line}\n{line}")
        assert cleaned.count(line) == 1

    def test_chunk_size(self):
        """chunk大小不超过设定值太多"""
        text = "这是一段很长的政策文本。" * 200
        chunks = chunk_policy_text(text, chunk_size=800, overlap=150)
        for chunk in chunks:
            assert len(chunk["text"]) <= 1000  # 允许少量超出

    def test_chunk_metadata(self):
        """chunk应包含元数据"""
        text = "政策内容第一条。\n政策内容第二条。"
        chunks = chunk_policy_text(text, doc_source="test.pdf", doc_date="2024-01-01")
        for chunk in chunks:
            assert chunk["metadata"]["source"] == "test.pdf"
            assert chunk["metadata"]["date"] == "2024-01-01"

    def test_chunk_overlap(self):
        """相邻chunk应有重叠"""
        text = "A" * 1000
        chunks = chunk_policy_text(text, chunk_size=400, overlap=100)
        if len(chunks) >= 2:
            # 第二个chunk的开头应与第一个chunk的结尾有重叠
            assert chunks[1]["text"][:50] in chunks[0]["text"]


class TestVectorStore:
    def test_init(self, tmp_path):
        """向量库应能初始化"""
        from src.rag.vector_store import PolicyVectorStore
        vs = PolicyVectorStore(persist_dir=str(tmp_path / "test_chroma_db"))
        stats = vs.get_stats()
        assert "total_chunks" in stats
        assert "embedding_model" in stats

    def test_transport_title_receives_higher_lexical_score(self):
        query = "交通运输行业碳达峰目标"
        transport = _lexical_relevance(
            query,
            "推动交通运输绿色低碳转型，助力实现碳达峰目标。",
            "交通运输碳达峰实施方案.md",
        )
        trading = _lexical_relevance(
            query,
            "重点排放单位应当按时清缴碳排放配额。",
            "碳排放权交易管理办法.md",
        )
        assert transport > trading


def test_retrieval_fallback_is_an_actual_sourced_answer():
    answer = build_retrieval_answer(
        "交通运输碳达峰目标是什么",
        [{
            "text": "交通运输行业要加快形成绿色低碳运输方式。",
            "metadata": {"source": "交通运输碳达峰实施方案.md", "date": "2022"},
        }],
    )
    assert "政策原文摘录" in answer
    assert "交通运输碳达峰实施方案.md" in answer
    # 适用性提示已改为条件触发：只有命中发电/电网/钢铁等行业履约规定时才出现。
    # 交通/重卡类文件的检索结果不该挂一段与问题无关的模板（见 tests/test_llm_resilience.py
    # 的 TestApplicabilityNoteIsNotAConstantTail）。
    assert "适用性提示" not in answer
    assert "请在 .env" not in answer
