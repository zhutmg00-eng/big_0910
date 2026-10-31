# -*- coding: utf-8 -*-
"""把 obsidian_staging/ 的 9 篇笔记通过 Obsidian CLI 推送到 vault。

用法：.venv/Scripts/python.exe 中期答辩后调研/push_to_obsidian.py [vault名称]
- 默认推到最近聚焦的 vault；可传 vault 名称显式指定。
- 目录：vault 内「大创-物流碳助手/」
"""
import subprocess
import sys
from pathlib import Path

CLI = r"D:\Obsidian\Obsidian.com"
STAGING = Path(__file__).resolve().parent / "obsidian_staging"
VAULT_DIR = "大创-物流碳助手"

def main():
    vault = sys.argv[1] if len(sys.argv) > 1 else None
    files = sorted(STAGING.glob("*.md"))
    if not files:
        print("没有待推送文件"); return 1
    ok, fail = 0, []
    for f in files:
        content = f.read_text(encoding="utf-8")
        args = [CLI, "create", f"path={VAULT_DIR}/{f.name}", f"content={content}", "silent", "overwrite"]
        if vault:
            args.insert(2, f"vault={vault}")
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=60)
        if r.returncode == 0:
            ok += 1
            print(f"  ✓ {f.name}")
        else:
            fail.append((f.name, (r.stderr or r.stdout or "").strip()[:200]))
            print(f"  ✗ {f.name}: {fail[-1][1]}")
    print(f"\n推送完成：{ok}/{len(files)}")
    return 0 if not fail else 2

if __name__ == "__main__":
    sys.exit(main())
