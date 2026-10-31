# -*- coding: utf-8 -*-
"""把 obsidian_staging/ 的笔记推送到 Obsidian vault。

用法：.venv/Scripts/python.exe 中期答辩后调研/push_to_obsidian.py [vault名称]
- 默认 vault：命令行参数 > %APPDATA%/obsidian/obsidian.json 中 open:true 的 vault
- 目录：vault 内「大创-物流碳助手/」

历史教训（2026-10-31）：旧版走 Obsidian CLI `create content=...` 传参，
9 篇报成功实际只落盘 7 篇，另有 1 篇被截断 17 字节——CLI 参数传递对长文本
不可靠且失败静默。现改为直写 vault 文件（Obsidian 监听文件系统自动刷新），
并在推送后逐篇做字节数校验，缺失或截断立即报错退出。
"""
import json
import os
import sys
from pathlib import Path

STAGING = Path(__file__).resolve().parent / "obsidian_staging"
VAULT_DIR = "大创-物流碳助手"
OBSIDIAN_CONFIG = Path(os.environ.get("APPDATA", "")) / "obsidian" / "obsidian.json"


def resolve_vault_path(vault_name):
    """从 Obsidian 全局配置解析 vault 路径。"""
    if not OBSIDIAN_CONFIG.exists():
        sys.exit(f"未找到 Obsidian 配置：{OBSIDIAN_CONFIG}")
    vaults = json.loads(OBSIDIAN_CONFIG.read_text(encoding="utf-8")).get("vaults", {})
    if vault_name:
        for v in vaults.values():
            if Path(v.get("path", "")).name == vault_name:
                return Path(v["path"])
        known = "、".join(sorted(Path(v.get("path", "")).name for v in vaults.values()))
        sys.exit(f"未找到名为「{vault_name}」的 vault。已知 vault：{known}")
    # 未指定名称：优先 open:true 的 vault
    for v in vaults.values():
        if v.get("open"):
            return Path(v["path"])
    sys.exit("obsidian.json 中没有 open:true 的 vault，请显式传入 vault 名称")


def main():
    vault_name = sys.argv[1] if len(sys.argv) > 1 else None
    vault = resolve_vault_path(vault_name)
    target_dir = vault / VAULT_DIR
    target_dir.mkdir(parents=True, exist_ok=True)

    files = sorted(STAGING.glob("*.md"))
    if not files:
        print("没有待推送文件"); return 1

    print(f"目标 vault：{vault.name} → {VAULT_DIR}/")
    ok, fail = 0, []
    for f in files:
        content = f.read_bytes()
        target = target_dir / f.name
        target.write_bytes(content)
        written = target.stat().st_size if target.exists() else -1
        if written == len(content):
            ok += 1
            print(f"  ✓ {f.name}（{written} 字节，校验一致）")
        else:
            fail.append((f.name, f"预期 {len(content)} 字节，实际 {written}"))
            print(f"  ✗ {f.name}: {fail[-1][1]}")

    print(f"\n推送完成：{ok}/{len(files)}（vault={vault.name}）")
    return 0 if not fail else 2


if __name__ == "__main__":
    sys.exit(main())
