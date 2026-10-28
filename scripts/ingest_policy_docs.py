#!/usr/bin/env python3
"""RAG 知识库入库脚本：将 data/policy_docs 下全部政策文档导入向量库。

用法：
  python scripts/ingest_policy_docs.py           # 增量：按内容哈希跳过未变文档（启动器可反复调用，秒级完成）
  python scripts/ingest_policy_docs.py --force   # 清空后全量重建
"""
import argparse
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import POLICY_DOCS_DIR  # noqa: E402
from src.rag import ingest_directory  # noqa: E402
from src.rag.vector_store import get_vector_store  # noqa: E402


def ingest_all(force: bool = False) -> dict:
    vs = get_vector_store()
    t0 = time.time()
    print(f"嵌入模型: {vs.embedding_model}  |  入库前: {vs.count()} 个文档块")
    summary = ingest_directory(POLICY_DOCS_DIR, vs, force=force)
    print(f"✅ 本次入库 {summary['documents']} 份 / {summary['chunks']} 块；"
          f"内容未变跳过 {summary['skipped']} 份；移除 {summary['removed']} 份；"
          f"知识库现有 {summary['kb_documents']} 份 / {summary['kb_chunks']} 块，"
          f"耗时 {time.time() - t0:.1f}s")
    # 被拒绝的文件必须显式列出来。它们不进知识库，所以「入库成功」这句话
    # 本身没错——但只打印成功数，运维会以为语料齐了，实际少了几份。
    # 实测 2026-10-29：两份 404 错误页被守卫静默挡在门外，没有任何提示。
    rejected = summary.get("rejected") or []
    if rejected:
        print(f"\n⚠️  {len(rejected)} 份文件被拒绝入库（内容为错误页，不是政策正文）：")
        for item in rejected:
            print(f"   - {item['file']}（命中「{item['marker']}」）")
        print("   处理方式见 data/policy_docs_unavailable/README.md")
    print(f"知识库统计: {vs.get_stats()}")
    for query in ["物流企业碳排放怎么计算", "新能源车需要交碳配额吗", "交通运输碳达峰目标"]:
        print(f"\n❓ {query}")
        for i, r in enumerate(vs.search(query, k=2), 1):
            print(f"  [{i}] {r['metadata'].get('source')} ({'+'.join(r.get('retrievers', []))})")
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force", action="store_true", help="清空后全量重建")
    ingest_all(force=parser.parse_args().force)
