#!/usr/bin/env python3
"""RAG知识库入库脚本 — 将政策文档导入ChromaDB

使用方法：
  pip install chromadb PyMuPDF beautifulsoup4
  python3 scripts/ingest_policy_docs.py
"""
import sys
from pathlib import Path
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# 确保src在路径中
sys.path.insert(0, str(Path(__file__).parent.parent))
from src.rag.parser import process_document
from src.rag.vector_store import PolicyVectorStore

POLICY_DOCS_DIR = Path(__file__).parent.parent / "data" / "policy_docs"

def ingest_all(force: bool = False):
    """将所有政策文档导入知识库"""
    vs = PolicyVectorStore()
    
    # 检查已有数量
    stats = vs.get_stats()
    print(f"当前知识库: {stats['total_chunks']} 个文档块")
    
    # 如果指定 force 或文档块数量不等于 268，清空并重新导入全量 37 份文档
    if force or stats['total_chunks'] != 268:
        print("知识库未收录全量文档或指定 force，清空并导入全量政策文档...")
        vs.clear()
    else:
        print("已有全量 268 个文档块，跳过重复导入。")
        return
    md_files = sorted(POLICY_DOCS_DIR.glob("*.md"))
    total_chunks = 0
    
    for md_file in md_files:
        if md_file.name.startswith("download_log") or md_file.name.startswith("supplement"):
            continue
        
        print(f"\n📄 {md_file.name}")
        
        # 提取日期（从文件名或内容中）
        date = ""
        for kw in ["2026", "2025", "2024", "2023", "2022", "2021", "2020"]:
            if kw in md_file.name:
                date = kw
                break

        chunks = process_document(md_file, date)
        if not chunks:
            print("  ⏭️  无有效内容，跳过")
            continue
        
        vs.add_documents(chunks, md_file.name, date)
        total_chunks += len(chunks)
    
    print(f"\n{'='*50}")
    print(f"✅ 导入完成: {total_chunks} 个文档块")
    print(f"知识库统计: {vs.get_stats()}")
    
    # 测试检索
    print(f"\n{'='*50}")
    print("🔍 测试检索...")
    test_queries = [
        "物流企业碳排放怎么计算",
        "碳配额不够怎么办",
        "新能源车需要交碳配额吗",
        "碳交易罚款标准",
        "交通运输碳达峰目标",
    ]
    
    for query in test_queries:
        print(f"\n❓ {query}")
        results = vs.search(query, k=2)
        for i, r in enumerate(results, 1):
            source = r["metadata"].get("source", "未知")
            text_preview = r["text"][:100].replace("\n", " ")
            print(f"  [{i}] {source}: {text_preview}...")

if __name__ == "__main__":
    ingest_all()
