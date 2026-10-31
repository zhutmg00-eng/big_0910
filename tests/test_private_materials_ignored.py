"""私用材料必须被 .gitignore 覆盖，且不得已经被跟踪。

背景（真实暴露，实测于 2026-10-31）：
`.gitignore` 里写着「私人研究、论文手稿与答辩私用文书产物（不上传Git）」，
但其中的 `docs/*答辩*.md` 只匹配 **docs/ 下的一层文件**，不覆盖子目录。
于是 `docs/中期答辩材料/` 里的逐字稿、问答预案、口径卡与禁语全部漏网；
同理 `docs/artifacts/*.png` 只匹配一层，`docs/artifacts/signatures/` 下
4 份真人签名图（sig_chen / sig_wang / sig_wangxx / sig_zhang）也未被忽略。

一次 `git add -A` 就会把这些推到公开仓库。签名与答辩预案一旦公开不可撤回
（GitHub 会缓存、可能被索引），因此用测试锁住，而不是靠人记得。

判据用 `git check-ignore`，与 git 自身行为一致，不另写一套 glob 解释器。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _is_ignored(rel: str) -> bool:
    """用 git 自己的规则判断，避免自造 glob 语义。"""
    proc = subprocess.run(
        ["git", "check-ignore", "-q", rel],
        cwd=ROOT, capture_output=True, text=True,
    )
    return proc.returncode == 0


#: 必须被忽略的路径（按目录给出代表样本，目录规则生效即可覆盖全部内容）
PRIVATE_SAMPLES = (
    "docs/artifacts/signatures/sig_chen.png",
    "docs/artifacts/signatures/sig_wang.png",
    "docs/中期答辩材料/00_五分钟架构与配时.md",
    "docs/中期答辩材料/01_逐字稿_5分钟.md",
    "docs/中期答辩材料/02_口径卡与禁语.md",
    "docs/expert_review/专家盲评综合评估与意见采纳报告.md",
    ".env",
    "data/chroma_db/chroma.sqlite3",
)


@pytest.mark.parametrize("rel", PRIVATE_SAMPLES)
def test_private_materials_are_ignored(rel: str) -> None:
    assert _is_ignored(rel), (
        f"{rel} 未被 .gitignore 覆盖——一次 git add -A 就会把它推上公开仓库。"
        "签名图与答辩预案属于私用材料，公开后不可撤回。"
    )


class TestPrivateDirsHoldNoTrackedFiles:
    """被忽略的目录里不能已经存在被跟踪的文件（历史遗留同样危险）。"""

    PRIVATE_DIRS = ("docs/artifacts/signatures", "docs/中期答辩材料", "docs/expert_review")

    def test_no_tracked_files_inside(self) -> None:
        tracked = subprocess.run(
            ["git", "ls-files"], cwd=ROOT, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        ).stdout.splitlines()
        offenders = [
            f for f in tracked
            if any(f.replace("\\", "/").startswith(d + "/") for d in self.PRIVATE_DIRS)
        ]
        assert not offenders, (
            f"这些私用材料已被 git 跟踪，需要 git rm --cached：{offenders}"
        )
