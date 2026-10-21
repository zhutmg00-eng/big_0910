"""清理换嵌入模型后遗留的历史 collection。

背景：``PolicyVectorStore`` 的 collection 名由嵌入模型哈希派生
（``carbon_policy_v5_<hash>``）。每换一次嵌入模型，``get_or_create_collection``
就会新建一份，旧的语料仍留在同一个 sqlite 里但不再被读到。这些历史
collection 不影响检索正确性，却会持续占盘，并让 ``/api/kb/health`` 的
``other_collections`` 越来越长，反而看不清「库为什么空了」。

用法：

    python scripts/prune_kb_collections.py            # 只列出，不删除
    python scripts/prune_kb_collections.py --apply    # 真正删除

删除不可逆。删之前请确认当前 collection 已经是健康的（先跑一次
``python scripts/ingest_policy_docs.py`` 并检查 ``/api/kb/health``）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# 确保在 Windows 默认 GBK 终端下直接运行或子进程调用时不会触发 Unicode 编码崩溃
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
if hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.rag.vector_store import PolicyVectorStore  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="清理历史 collection")
    parser.add_argument("--apply", action="store_true", help="真正删除（默认只预览）")
    parser.add_argument("--persist-dir", default=None, help="覆盖 ChromaDB 目录")
    args = parser.parse_args()

    store = PolicyVectorStore(args.persist_dir) if args.persist_dir else PolicyVectorStore()
    health = store.health()
    print(f"当前 collection: {health['collection_name']}  "
          f"({health['count']} 块 / {health['documents']} 份文档)  status={health['status']}")

    if health["count"] == 0:
        print("当前 collection 是空的，先跑 python scripts/ingest_policy_docs.py 建库，"
              "否则清理后可能一份语料都不剩。已中止。")
        return 1

    plan = store.prune_stale_collections(dry_run=not args.apply)
    if plan.get("error"):
        print("无法列举 collection：", plan["error"])
        return 1
    if not plan["removed"]:
        print("没有历史 collection 需要清理。")
        return 0

    print()
    print("历史 collection（不被当前配置读取）：")
    for name, count in sorted(plan["removed"].items()):
        print(f"  {name:40s} {count:>6} 块")

    if not args.apply:
        print()
        print("以上仅为预览，未删除任何数据。确认无误后加 --apply 执行。")
        return 0

    print()
    print(f"已删除 {len(plan['removed'])} 份历史 collection，"
          f"释放 BM25 缓存 {plan['freed_bytes']:,} 字节。")
    after = store.health()
    print(f"清理后：{after['collection_name']} {after['count']} 块，status={after['status']}")
    if after["count"] != health["count"]:
        print("警告：当前 collection 块数与清理前不一致，请复查。")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
