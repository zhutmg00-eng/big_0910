"""迭代自检：一条命令回答「现在还能不能安全地继续改」。

覆盖三件事，任何一项失败都返回非零退出码：
1. ruff 全通过（src / tests / scripts）；
2. 全量测试通过，且答辩载体里的测试数与实测一致；
3. 知识库非空且规模与文档声明一致（空库会让 2 项 RAG 基准测试跳过而非失败，
   是「看起来绿、其实没验」的典型场景）。

CI 与本地解释器不同（3.11 vs 3.10），因此本脚本只代表本机状态；
远端结论以 GitHub Actions 运行记录为准。

用法：
    python scripts/selfcheck.py            # 全量
    python scripts/selfcheck.py --fast     # 跳过 RAG 基准回归
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = sys.executable

FAIL = "FAIL"
OK = "OK"


def _run(args: list[str], cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run(
        [PY, *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )


def check_lint() -> tuple[str, str]:
    proc = _run(["-m", "ruff", "check", "src", "tests", "scripts"])
    if proc.returncode != 0:
        return FAIL, (proc.stdout or proc.stderr).strip()[-1500:]
    return OK, "ruff 全通过"


def check_tests() -> tuple[str, str]:
    proc = _run(["-m", "pytest", "-q"])
    tail = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
    if proc.returncode != 0:
        failed = re.findall(r"FAILED (\S+)", proc.stdout or "")
        return FAIL, f"{tail}\n" + "\n".join(failed[:10])
    return OK, tail


def check_counts_synced() -> tuple[str, str]:
    """答辩载体里的测试数必须与实测一致（否则守卫会红，这里提前暴露）。"""
    proc = _run([str(ROOT / "scripts" / "sync_deck_test_count.py"), "--check"])
    out = (proc.stdout or proc.stderr).strip()
    return (OK if proc.returncode == 0 else FAIL), out[-1200:]


def check_kb() -> tuple[str, str]:
    """知识库非空，且块数与 RAG 结果文件记录的一致。"""
    try:
        sys.path.insert(0, str(ROOT))
        from src.rag.vector_store import PolicyVectorStore

        stats = PolicyVectorStore().get_stats()
    except Exception as exc:  # pragma: no cover - 环境异常直接报出
        return FAIL, f"无法初始化知识库：{exc}"

    chunks, docs = stats.get("total_chunks", 0), stats.get("total_documents", 0)
    if chunks == 0:
        return FAIL, (
            "知识库为空：政策问答会返回空结果，2 项 RAG 基准测试将 skip 而非失败。"
            "先运行 python scripts/ingest_policy_docs.py --force"
        )

    results = ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json"
    if results.exists():
        import json

        meta = json.loads(results.read_text(encoding="utf-8")).get("benchmark_metadata", {})
        want = meta.get("total_chunks")
        if want and want != chunks:
            return FAIL, (
                f"知识库 {chunks} 块，但评测结果记录的是 {want} 块——"
                "指标与当前语料不同源，必须重跑 evaluate_rag_benchmark.py"
            )
    return OK, f"{docs} 份 / {chunks} 块，与评测结果同源"


def check_ci_pointer() -> tuple[str, str]:
    """提醒：本机绿灯不等于远端绿灯，两者解释器不同。"""
    return OK, "远端状态需另查 GitHub Actions（本机 Python 与 CI 的 3.11 不同）"


def main() -> int:
    fast = "--fast" in sys.argv
    checks = [
        ("lint", check_lint),
        ("tests", check_tests),
        ("counts", check_counts_synced),
        ("kb", check_kb),
        ("ci", check_ci_pointer),
    ]
    if fast:
        checks = [c for c in checks if c[0] not in {"tests"}]

    results = []
    for name, fn in checks:
        status, detail = fn()
        results.append((name, status, detail))
        mark = "✅" if status == OK else "❌"
        print(f"{mark} {name}: {detail.splitlines()[0] if detail else ''}")

    failed = [r for r in results if r[1] == FAIL]
    print()
    if failed:
        print(f"自检未通过：{len(failed)}/{len(results)} 项失败")
        for name, _, detail in failed:
            print(f"\n--- {name} ---\n{detail}")
        return 1
    print(f"自检通过：{len(results)}/{len(results)} 项")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
