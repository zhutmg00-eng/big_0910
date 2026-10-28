"""模块可达性：`src/` 下每个模块都必须能从入口走得到。

背景（2026-10-27，I-1）：
`src/rag/crawler.py`（84 行，含浏览器 UA 伪装且未检查 robots.txt）与
`src/models/carbon.py`（48 行，字段与 `src/engine/calculator.py` 的 dataclass
重复）在仓库里躺了很久，没有任何模块 import 它们——`grep -rn crawler src scripts tests`
除自身外零命中，但 `docs/architecture.md` 仍把 crawler 列在 RAG 链路里。
评审按文档读代码会找不到调用链，而爬虫本身还有合规问题。

本文件从 `src/` 的真实入口出发做可达性遍历：只要某个模块无法从
`src/api/main.py`、`src/cli`、`scripts/` 或 `src/ui/app.py` 间接到达，
它就应当是死代码。

白名单只放**有明确在场理由**的模块，且理由要写在注释里；新增一条白名单
等于承认"这个模块没有调用方"，必须同时说明它为何仍要保留。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"

#: 允许「无人 import」但仍保留的模块，键为相对 src/ 的路径。
#: 空则代表 src/ 下不应存在不可达模块。
ALLOWLIST: dict[str, str] = {}


def _module_name(path: Path) -> str:
    rel = path.relative_to(ROOT).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _imports_of(path: Path) -> set[str]:
    """解析文件里的 import，返回被引用的模块前缀（只取 src 内部）。"""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:  # pragma: no cover - 语法错误由 ruff/编译期暴露
        return set()

    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            # 相对导入（from . import x / from ..engine import y）按包名还原
            if node.level and node.module:
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                pkg = ".".join(base.relative_to(ROOT).parts)
                found.add(f"{pkg}.{node.module}")
            elif node.level:
                base = path.parent
                for _ in range(node.level - 1):
                    base = base.parent
                pkg = ".".join(base.relative_to(ROOT).parts)
                found.add(pkg)
                for alias in node.names:
                    found.add(f"{pkg}.{alias.name}")
            elif node.module:
                found.add(node.module)
                for alias in node.names:
                    found.add(f"{node.module}.{alias.name}")
    return found


def _reachable() -> set[str]:
    """从真实入口做可达性遍历，返回可达模块名集合。

    包的 `__init__.py` 不需要被显式 import：只要包内有任一模块可达，
    该包本身就已经被加载（Python 导入子模块必然先执行父包）。
    因此判定时把「可达模块名的前缀包」一并算作可达。
    """
    entries = [
        SRC / "api" / "main.py",
        SRC / "ui" / "app.py",
    ]
    entries += list((ROOT / "scripts").glob("*.py"))
    entries += list(SRC.glob("__init__.py"))

    by_name: dict[str, Path] = {}
    for py in SRC.rglob("*.py"):
        by_name[_module_name(py)] = py

    queue = [e for e in entries if e.exists()]
    seen: set[str] = set()
    while queue:
        current = queue.pop()
        name = _module_name(current) if current.is_relative_to(ROOT) else ""
        if name in seen:
            continue
        seen.add(name)

        for imported in _imports_of(current):
            # 把 a.b.c 逐级回退到实际存在的模块文件
            probe = imported
            target = None
            while probe and target is None:
                target = by_name.get(probe)
                if target is None:
                    probe = probe.rpartition(".")[0]
            if target is None:
                continue
            key = _module_name(target)
            if key not in seen:
                queue.append(target)
    return seen


def test_all_src_modules_are_reachable() -> None:
    """src/ 下不应存在无法从任何入口到达的模块。"""
    reachable = _reachable()
    # 包本身随其子模块一起加载，因此「是某个可达模块的父包」即视为可达
    packages = {
        name.rpartition(".")[0] for name in reachable if "." in name
    }

    unreachable = []
    for py in sorted(SRC.rglob("*.py")):
        name = _module_name(py)
        if name in reachable or name in packages or name in ALLOWLIST:
            continue
        unreachable.append(f"{py.relative_to(ROOT)}（{name}）")

    assert not unreachable, (
        "以下模块无法从 src/api/main.py、src/ui/app.py、scripts/ 或包的 __init__ 到达，"
        "属于死代码：\n  " + "\n  ".join(unreachable) + "\n"
        "若要保留，请在 ALLOWLIST 里写明理由。"
    )


def test_architecture_doc_does_not_list_removed_modules() -> None:
    """架构文档不得再把已删除的模块**当作现有模块**列出。

    材料里允许留「早期存在过 X，已删除」这类撤回记录（学术诚信要求留痕），
    要拦的是把它继续写在模块清单里、让读者以为它还在用。
    """
    doc = (ROOT / "docs" / "architecture.md").read_text(encoding="utf-8")
    retract_markers = ("已删除", "早期存在过", "曾存在", "不再维护")

    for gone in ("crawler.py", "models/carbon.py"):
        if (SRC / "rag" / "crawler.py").exists() or (SRC / "models" / "carbon.py").exists():
            continue  # 文件还在（例如被恢复），本条不适用
        for line in doc.splitlines():
            if gone not in line:
                continue
            if any(m in line for m in retract_markers):
                continue
            raise AssertionError(
                f"architecture.md 仍把已删除的 {gone} 列为现有模块：{line.strip()[:120]}"
            )


@pytest.mark.parametrize("module", ["src.models.carbon", "src.rag.crawler"])
def test_removed_modules_stay_removed(module: str) -> None:
    """锁住删除决定：这两个模块曾被误认为在用，实际零引用。"""
    with pytest.raises(ModuleNotFoundError):
        __import__(module)


# ---------------------------------------------------------------- CI 单一来源（I-4）

class TestSingleSourceOfWorkflow:
    """CI 只有一份定义，文档不得把已删除的模板当作现状引用。

    背景（2026-10-27，I-4）：仓库曾有 `.github/workflows/ci.yml`（含字体安装、
    ruff、政策入库、覆盖率、RAG 基准回归）与 `docs/ci-workflow-template.yml`
    （仅 install + pytest）并存。两者内容早已分叉，而 README 曾把后者当作
    「CI 是否启用」的证据，与实际 47 次远端运行记录矛盾。
    """

    WORKFLOWS = ROOT / ".github" / "workflows"
    TEMPLATE = ROOT / "docs" / "ci-workflow-template.yml"

    def test_only_one_workflow_exists(self) -> None:
        files = sorted(p.name for p in self.WORKFLOWS.glob("*.yml"))
        assert files == ["ci.yml"], f"workflows 目录应只有 ci.yml，实际 {files}"

    def test_template_stays_deleted(self) -> None:
        assert not self.TEMPLATE.exists(), (
            "docs/ci-workflow-template.yml 已被删除：它与真实流水线内容分叉，"
            "留着会被当作「CI 未启用」的证据。若确实需要模板，请先更新本测试的理由。"
        )

    def test_workflow_covers_the_four_gates(self) -> None:
        """真实流水线必须覆盖四道闸门，否则「CI 绿」不足以说明质量。"""
        text = (self.WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
        for gate in ("ruff", "ingest_policy_docs.py", "pytest", "evaluate_rag_benchmark.py"):
            assert gate in text, f"CI 缺少 {gate} 这一步"

    def test_docs_mentioning_template_mark_it_removed(self) -> None:
        """文档里若提到该模板，必须同时说明已删除，不能当现状。"""
        for rel in ("README.md", "HANDOVER.md"):
            text = (ROOT / rel).read_text(encoding="utf-8")
            for line in text.splitlines():
                if "ci-workflow-template" not in line:
                    continue
                window = text[max(0, text.find(line) - 300): text.find(line) + 400]
                assert any(m in window for m in ("已删除", "不存在")), (
                    f"{rel} 提到 ci-workflow-template.yml 但未说明已删除"
                )
