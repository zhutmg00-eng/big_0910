"""把答辩载体里的测试数回写为 pytest 实测值，杜绝手写「N 项全绿」。

展板是静态 HTML，测试数以 ``<span data-test-count="collected|passed|skipped">`` 标记；
私有答辩文书（被 .gitignore 排除，只在本地存在）里的「N 项测试」是普通正文，
靠正则回写。两处都在本脚本里统一到同一次实测。

- collected：pytest 收集到的测试总数；
- passed / skipped：在**当前环境**下的通过数与跳过数。公开仓库缺少被 .gitignore
  排除的私有文书与真实 API Key，因此一定会有跳过项——如实写出来，而不是写「全绿」。

私有文书缺失时跳过该文件（CI/全新 clone 上本来就没有），不算失败。

用法：
    python scripts/sync_deck_test_count.py           # 实跑并回写
    python scripts/sync_deck_test_count.py --check   # 只检查，不一致时退出码 1
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DECK = ROOT / "docs" / "artifacts" / "defense_presentation_deck.html"
SPAN = re.compile(r'(<span data-test-count="(collected|passed|skipped)">)(\d+)(</span>)')

#: 私有答辩文书里的测试数写法：「427 项测试」「436 项自动化测试」「**415 项全自动…」
PROSE_COUNT = re.compile(r"(\d+)(\s*项[^。；\n]{0,8}?测试|\s*项测试)")


def _cjk_prose_files() -> list[Path]:
    """本地存在的私有答辩文书。缺失即跳过，不报错。"""
    return [
        p for p in sorted((ROOT / "docs").glob("*答辩*.md"))
        if p.is_file() and p.name != "rag_retrieval_experiment_report.md"
    ]



#: 这两条守卫**用载体里的数字**做断言，所以它们必然带着旧值失败，
#: 回写前必须绕开；否则脚本死锁——回写要求零失败，而唯一失败就是「还没回写」。
COUNT_GUARDS = (
    "tests/test_claim_consistency.py::test_defense_docs_test_count_matches_collection",
    "tests/test_defense_wording_guards.py::test_deck_test_counts_are_script_synced",
)


def _run(args: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", *args],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )


def _tally(proc: subprocess.CompletedProcess) -> dict[str, int]:
    tail = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
    counts = {k: int(v) for v, k in re.findall(r"(\d+) (passed|skipped|failed|errors?)", tail)}
    return {
        "passed": counts.get("passed", 0),
        "skipped": counts.get("skipped", 0),
        "failed": (counts.get("failed", 0) + counts.get("error", 0) + counts.get("errors", 0)),
    }


def collect_count() -> int:
    """只用 collect-only 取「收集数」，与 test_claim_consistency 里的口径一致。"""
    proc = _run(["--collect-only"])
    for line in reversed((proc.stdout or "").splitlines()):
        m = re.search(r"(\d+) tests? collected", line)
        if m:
            return int(m.group(1))
    raise SystemExit(f"无法从 pytest 取得收集数：{(proc.stdout or '')[-400:]}")


def measure() -> dict[str, int]:
    """绕过两条计数守卫跑一次，得到与载体内容无关的通过/跳过数。

    展板要求 ``collected == passed + skipped``，所以 passed 由
    ``collected - skipped`` 推出（被绕开的守卫在回写后必然通过）。
    """
    tally = _tally(_run(["--deselect", COUNT_GUARDS[0], "--deselect", COUNT_GUARDS[1]]))
    collected = collect_count()
    tally["collected"] = collected
    if not tally["failed"]:
        tally["passed"] = collected - tally["skipped"]
    return tally


def verify() -> dict[str, int]:
    """回写后按全量（含守卫）复跑，作为「确实全绿」的证据。"""
    return _tally(_run([]))


def main() -> int:
    counts = measure()
    text = DECK.read_text(encoding="utf-8")
    new = SPAN.sub(lambda m: f"{m.group(1)}{counts[m.group(2)]}{m.group(4)}", text)

    prose = {}
    for path in _cjk_prose_files():
        src = path.read_text(encoding="utf-8")
        updated = PROSE_COUNT.sub(lambda m: f"{counts['collected']}{m.group(2)}", src)
        prose[path] = (src, updated)

    if "--check" in sys.argv:
        stale = []
        if new != text:
            stale.append("展板（docs/artifacts/defense_presentation_deck.html）")
        stale += [str(p.relative_to(ROOT)) for p, (old, upd) in prose.items() if old != upd]
        if stale:
            print(f"测试数与实测 {counts} 不一致：")
            for name in stale:
                print(f"  - {name}")
            return 1
        print(f"一致：{counts}")
        return 0

    if counts["failed"]:
        raise SystemExit(f"测试未全部通过，拒绝回写答辩载体：{counts}")

    backups = {p: p.read_text(encoding="utf-8") for p in [DECK, *prose]}
    if new != text:
        DECK.write_text(new, encoding="utf-8")
        print("已回写展板")
    for path, (old, upd) in prose.items():
        if old != upd:
            path.write_text(upd, encoding="utf-8")
            print(f"已回写 {path.relative_to(ROOT)}")
    print(f"已写入 {counts}")

    # 回写后必须全量复跑：只写数字不验证，等于把「全绿」当假设
    after = verify()
    if after["failed"]:
        for p, body in backups.items():
            p.write_text(body, encoding="utf-8")
        raise SystemExit(f"回写后仍有 {after['failed']} 项失败，已还原全部载体：{after}")
    print(f"全量复跑通过：{after}")
    return 0
    if new != text:
        DECK.write_text(new, encoding="utf-8")
        print("已回写展板")
    for path, (old, upd) in prose.items():
        if old != upd:
            path.write_text(upd, encoding="utf-8")
            print(f"已回写 {path.relative_to(ROOT)}")
    print(f"已写入 {counts}")

    # 回写后必须全量复跑：只写数字不验证，等于把「全绿」当假设
    after = verify()
    if after["failed"]:
        for p, body in backups.items():
            p.write_text(body, encoding="utf-8")
        raise SystemExit(f"回写后仍有 {after['failed']} 项失败，已还原全部载体：{after}")
    print(f"全量复跑通过：{after}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
