"""插件包完整性回归测试（2026-09-08 修复项）

覆盖修复：
1. package.json 的 module/main/types 指向的文件必须存在
   （此前 "module": "dist/index.mjs" 指向缺失文件 → ESM loader 解析失败）
2. dist 产物不得残留顶层 await import('@deepseek-ai/dsh-tools')
   （顶层 await 会导致 CJS require(esm) 加载直接抛错 → 插件加载阻塞）
3. src 与 dist 不得残留硬编码个人开发机路径（"大创"）
4. dist 产物与 src 关键字同步（resolveDefineTool 存在）
"""
import json
from pathlib import Path

PKG_DIR = Path(__file__).parent.parent / "packages" / "dsh-plugin-carbon-asset"
SRC_DIR = PKG_DIR / "src"
DIST_DIR = PKG_DIR / "dist"

FORBIDDEN_PERSONAL_MARKERS = ["大创"]


class TestPluginPackage:
    def test_package_entry_points_exist(self):
        """main/types/module 指向的文件必须真实存在"""
        pkg = json.loads((PKG_DIR / "package.json").read_text(encoding="utf-8"))
        for field in ("main", "types"):
            assert field in pkg, f"package.json 缺少 {field} 字段"
            target = PKG_DIR / pkg[field]
            assert target.exists(), f"{field}={pkg[field]} 指向的文件不存在: {target}"
        if "module" in pkg:
            target = PKG_DIR / pkg["module"]
            assert target.exists(), f"module={pkg['module']} 指向的文件不存在: {target}"

    def test_dist_no_top_level_await_import(self):
        """dist 产物不得含顶层 await import（曾导致 CJS 加载阻塞）"""
        for f in sorted(DIST_DIR.glob("*.js")):
            text = f.read_text(encoding="utf-8")
            assert "await import(" not in text, f"{f.name} 含 await import("
            assert "await import (" not in text, f"{f.name} 含 await import ("

    def test_no_hardcoded_personal_paths(self):
        """src 与 dist 不得残留个人开发机路径标记"""
        for d in (SRC_DIR, DIST_DIR):
            for f in sorted(d.glob("*.ts")) + sorted(d.glob("*.js")):
                text = f.read_text(encoding="utf-8")
                for marker in FORBIDDEN_PERSONAL_MARKERS:
                    assert marker not in text, f"{f.name} 残留个人路径标记: {marker}"

    def test_resolve_define_tool_synced(self):
        """dist 产物应包含惰性解析函数（与 src 同步）"""
        src_text = (SRC_DIR / "index.ts").read_text(encoding="utf-8")
        dist_text = (DIST_DIR / "index.js").read_text(encoding="utf-8")
        assert "resolveDefineTool" in src_text
        assert "resolveDefineTool" in dist_text
        assert "await import('@deepseek-ai/dsh-tools')" not in src_text

    def test_all_six_tools_registered(self):
        """验证插件完整注册了 6 项核心碳资产工具"""
        expected_tools = [
            "carbon_calculate",
            "carbon_tco_evaluate",
            "carbon_reduction_scenario",
            "carbon_policy_query",
            "carbon_enterprise_compare",
            "carbon_turnover_evaluate",
        ]
        src_text = (SRC_DIR / "index.ts").read_text(encoding="utf-8")
        dist_text = (DIST_DIR / "index.js").read_text(encoding="utf-8")
        for tool in expected_tools:
            assert tool in src_text, f"src/index.ts 缺少工具: {tool}"
            assert tool in dist_text, f"dist/index.js 缺少工具: {tool}"
