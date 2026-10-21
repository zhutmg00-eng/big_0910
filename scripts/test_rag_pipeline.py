#!/usr/bin/env python3
"""RAG端到端验收：清洗、入库、混合检索和无 LLM 降级回答。

测试链路：政策文档 → 入库 → 检索 → 构建Prompt → （模拟）生成
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.rag.parser import process_document
from src.rag.vector_store import PolicyVectorStore
from src.rag.generator import build_retrieval_answer, build_user_prompt, SYSTEM_PROMPT

def test_rag_pipeline():
    print("=" * 60)
    print("🔍 RAG端到端检索质量验收")
    print("=" * 60)

    # === 1. 初始化知识库 ===
    print("\n📋 步骤1: 初始化知识库")
    vs = PolicyVectorStore()
    stats = vs.get_stats()
    print(f"  模式: {stats['mode']}")
    print(f"  文档块数: {stats['total_chunks']}")

    # === 2. 导入几份关键政策文档 ===
    if stats['total_chunks'] == 0:
        print("\n📋 步骤2: 导入政策文档")
        policy_dir = Path(__file__).parent.parent / "data" / "policy_docs"

        # 选择几份核心文档
        key_docs = [
            "碳排放权交易管理暂行条例.md",
            "碳排放权交易管理办法_试行_全文.md",
            "交通运输碳达峰实施方案.md",
            "公路水路营业性运输工具碳排放核算方法_征求意见稿.md",
            "温室气体自愿减排交易管理办法_试行.md",
            "2025年全国碳市场有关工作通知.md",
            "推进绿色低碳转型加强全国碳市场建设意见_2025.md",
            "十五五碳达峰行动方案_2026.md",
            "企业温室气体排放核算与报告指南_发电设施.md",
        ]
        total_chunks = 0
        for doc_name in key_docs:
            doc_path = policy_dir / doc_name
            if not doc_path.exists():
                print(f"  ⏭️  跳过: {doc_name}（不存在）")
                continue

            chunks = process_document(doc_path, doc_date="2025")

            vs.add_documents(chunks, doc_name, "2025")
            total_chunks += len(chunks)
            print(f"  ✅ {doc_name}: {len(chunks)} chunks")

        print(f"\n  总计导入: {total_chunks} 个文档块")
        stats = vs.get_stats()
        print(f"  知识库: {stats['total_chunks']} 个文档块 ({stats['mode']})")
    else:
        print(f"\n📋 步骤2: 跳过（已有 {stats['total_chunks']} 个文档块）")

    # === 3. 测试检索 ===
    print("\n📋 步骤3: 检索测试")

    test_queries = [
        "物流运输工具碳排放怎么核算",
        "物流企业模拟碳预算差额应如何理解",
        "碳交易市场罚款标准是什么",
        "交通运输行业碳达峰目标",
        "企业如何进行温室气体排放报告",
        "CCER自愿减排量怎么用",
    ]

    expected_top_sources = {
        "物流运输工具碳排放怎么核算": "公路水路营业性运输工具碳排放核算方法",
        "交通运输行业碳达峰目标": "交通运输碳达峰实施方案",
    }

    for query in test_queries:
        print(f"\n  ❓ {query}")
        results = vs.search(query, k=3)
        for i, r in enumerate(results, 1):
            source = r["metadata"].get("source", "未知")
            score = r.get("distance", 1)
            text_preview = r["text"][:120].replace("\n", " ")
            print(f"    [{i}] {source} (distance={score:.3f})")
            print(f"        {text_preview}...")
        expected = expected_top_sources.get(query)
        if expected:
            assert results, f"检索无结果: {query}"
            top_source = results[0]["metadata"].get("source", "")
            assert expected in top_source, (
                f"相关性验收失败: {query!r} 首条命中 {top_source!r}，期望 {expected!r}"
            )

    # === 4. 测试Prompt构建 ===
    print("\n📋 步骤4: Prompt构建测试")

    query = "我们公司有50辆重型柴油货车，年直接运营排放约3500吨，应该如何减排？"
    results = vs.search(query, k=3)

    carbon_profile = {
        "企业类型": "物流运输企业",
        "总车辆数": 50,
        "年度碳排放_t": 3500,
        "预算差额_t": 200,
        "情景状态": "超出预算",
        "情景成本_元": 15000,
    }

    user_prompt = build_user_prompt(query, results, carbon_profile)

    print(f"\n  用户问题: {query}")
    print(f"  检索结果: {len(results)} 个chunk")
    print(f"  Prompt长度: {len(user_prompt)} 字符")
    print("\n  --- System Prompt (前200字) ---")
    print(f"  {SYSTEM_PROMPT[:200]}...")
    print("\n  --- User Prompt (前500字) ---")
    print(f"  {user_prompt[:500]}...")

    # === 5. 无 LLM 降级回答 ===
    print("\n📋 步骤5: 无 LLM 降级回答")
    fallback_response = build_retrieval_answer(query, results)
    assert "政策原文摘录" in fallback_response
    # 适用性提示改为条件触发（命中其他行业履约规定时才提示），
    # 见 src/rag/generator.py 的 _applicability_note。
    assert "检索结论" in fallback_response
    print(fallback_response)

    print("\n" + "=" * 60)
    print(f"✅ RAG端到端测试完成（{stats['mode']}）")
    print("=" * 60)


if __name__ == "__main__":
    test_rag_pipeline()
