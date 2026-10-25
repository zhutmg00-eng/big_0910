"""把答辩展板里的测试数回写为 pytest 实测值，杜绝手写「N 项全绿」。

展板是静态 HTML，测试数以 ``<span data-test-count="collected|passed|skipped">`` 标记。
本脚本在当前环境实跑一次测试，按输出回写三个数：

- collected：pytest 收集到的测试总数；
- passed / skipped：在**当前环境**下的通过数与跳过数。公开仓库缺少被 .gitignore
  排除的私有文书与真实 API Key，因此一定会有跳过项——如实写出来，而不是写「全绿」。

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


def run_pytest() -> dict[str, int]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider"],
        cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    tail = (proc.stdout or "").strip().splitlines()[-1] if proc.stdout else ""
    counts = {k: int(v) for v, k in re.findall(r"(\d+) (passed|skipped|failed|errors?)", tail)}
    if counts.get("failed") or counts.get("error") or counts.get("errors"):
        raise SystemExit(f"测试未全部通过，拒绝回写展板：{tail}")
    passed, skipped = counts.get("passed", 0), counts.get("skipped", 0)
    return {"collected": passed + skipped, "passed": passed, "skipped": skipped}


def main() -> int:
    counts = run_pytest()
    text = DECK.read_text(encoding="utf-8")
    new = SPAN.sub(lambda m: f"{m.group(1)}{counts[m.group(2)]}{m.group(4)}", text)
    if "--check" in sys.argv:
        if new != text:
            print(f"展板测试数与实测不一致，实测 {counts}")
            return 1
        print(f"一致：{counts}")
        return 0
    DECK.write_text(new, encoding="utf-8")
    print(f"已回写 {counts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
