"""图表产物写入路径的唯一性守卫。

背景（真实事故）：docs/artifacts/fig4_baas_tco_comparison.svg 与
fig5_grid_scope2_green_power.svg 曾被两个脚本写同一个路径——
scripts/render_academic_figures.py（matplotlib，数字取自 docs/derived_metrics.json，
是论文与答辩引用的正式版本）和 scripts/generate_advanced_charts.py（早期手绘 SVG，
硬编码常量，且把 30 个省级行政区写成"31 省"）。
只要有人运行后者，论文引用的图就被静默替换成口径错误的旧图，而 git diff 只会
显示"图变了"，不会显示"图错了"。实测已发生过一次。

这些测试守住两点：
1. 早期脚本不再写正式产物名（必须带 _legacy 后缀）；
2. 论文正文引用的图必须真实存在，且确实带 matplotlib 生成标记。
"""
import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = REPO_ROOT / "docs" / "artifacts"

# 论文 / 答辩引用的正式图（文件名即契约）
FORMAL_FIGURES = (
    "fig4_baas_tco_comparison.svg",
    "fig5_grid_scope2_green_power.svg",
)

# 已被取代的早期脚本，以及它必须带上的后缀
LEGACY_WRITER = REPO_ROOT / "scripts" / "generate_advanced_charts.py"
FORMAL_WRITER = REPO_ROOT / "scripts" / "render_academic_figures.py"


def _read(path: Path) -> str:
    # 早期脚本必须入库：它是"谁在写正式产物"这条契约的一半，
    # 缺了它守卫就失效，所以缺失直接判失败。
    assert path.exists(), (
        f"{path.name} 必须随仓库发布，否则无法验证产物路径契约"
    )
    return path.read_text(encoding="utf-8")


def _read_formal_writer() -> str:
    # scripts/render_academic_figures.py 被 .gitignore 排除（与论文产物同级的
    # 私有出图脚本）。在公开 clone / CI 里它不存在，此时跳过而不是失败，
    # 但跳过原因要写清，免得 CI 绿得没有说服力。
    if not FORMAL_WRITER.exists():
        pytest.skip(
            "scripts/render_academic_figures.py 未入库"
            "（.gitignore 排除，属私有出图脚本），跳过该侧校验"
        )
    return FORMAL_WRITER.read_text(encoding="utf-8")


def test_legacy_writer_uses_suffixed_output_paths():
    """早期脚本写入的文件名必须与正式产物不同，否则会静默覆盖。"""
    source = _read(LEGACY_WRITER)

    # 找到所有 ARTIFACTS_DIR / "..." 形式的写盘目标
    targets = re.findall(r'ARTIFACTS_DIR\s*/\s*f?"([^"]+)"', source)
    assert targets, "未能在 generate_advanced_charts.py 中找到写盘目标，测试需同步更新"

    for target in targets:
        for formal in FORMAL_FIGURES:
            assert target != formal, (
                f"scripts/generate_advanced_charts.py 仍在直接写 {formal}——"
                f"这会覆盖 {FORMAL_WRITER.name} 生成的论文正式图，请加 _legacy 后缀"
            )


def test_legacy_writer_declares_it_is_superseded():
    """早期脚本的 docstring 必须说明它已被取代，避免后人当成正式出图脚本运行。"""
    docstring = (_read(LEGACY_WRITER).split('"""')[1] if '"""' in _read(LEGACY_WRITER)[:2000] else "")
    assert "已被取代" in docstring or "已被取代" in _read(LEGACY_WRITER)[:2000], (
        "generate_advanced_charts.py 顶部需注明已被 render_academic_figures.py 取代"
    )
    assert "render_academic_figures" in _read(LEGACY_WRITER)[:3000], (
        "需在文件顶部指向正式出图脚本 render_academic_figures.py"
    )


@pytest.mark.parametrize("name", FORMAL_FIGURES)
def test_formal_figure_exists_and_is_matplotlib_generated(name):
    """论文引用的图必须存在，且确实是 matplotlib 产物（不是手绘旧版）。"""
    path = ARTIFACTS / name
    if not path.exists():
        pytest.skip(f"{name} 未生成（先跑 python scripts/render_academic_figures.py）")

    head = path.read_text(encoding="utf-8", errors="replace")[:2000]
    assert "Matplotlib" in head, (
        f"{name} 缺少 matplotlib 生成标记，可能是被早期手绘图覆盖了。"
        f"请重新执行 python scripts/render_academic_figures.py"
    )


def test_formal_writer_does_not_write_legacy_names():
    """反过来：正式脚本不应产出 _legacy 后缀的文件。"""
    source = _read_formal_writer()
    assert "_legacy" not in source, (
        "render_academic_figures.py 不应写 _legacy 产物，_legacy 只属于被取代的旧脚本"
    )
