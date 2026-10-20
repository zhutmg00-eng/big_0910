"""预算差额口径警示的回归测试。

背景：模拟碳预算 B 用 CSV 里的**政策参考年均里程**计算，而排放 E 用用户
填报的**实际里程**计算（src/engine/quota.py 顶部 docstring 已声明此口径差异）。
当实际里程偏离参考值时，Gap 里混入"活动水平差异"，不是纯减排目标缺口。

API 早已在 carbon_budget["活动水平偏离_pct"] / ["口径说明"] 里算好这个偏离，
但 UI 从没渲染过——用户看到 +119,029 tCO2e 的差额，无从知道其中有多少
只是"跑得比参考值多"。这些测试守住：偏离超阈值时必须出现警示，未超时不得噪音。
"""
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.engine.quota import compute_activity_mismatch  # noqa: E402


def _result(mismatch_pct):
    """构造一个最小可渲染的核算结果，只控制口径偏离字段。"""
    return {
        "total_emission_t": 47768.0,
        "total_vehicles": 50,
        "emission_by_type": {},
        "carbon_budget": {
            "模拟碳预算_t": 239619.0,
            "预算差额_t": 119029.0,
            "状态": "超出模拟碳预算",
            "活动水平偏离_pct": mismatch_pct,
        },
    }


def _render_warnings(result):
    """用 streamlit AppTest 在 bare 模式渲染总览页，返回所有 warning 文本。"""
    from streamlit.testing.v1 import AppTest

    # 子脚本需要自己把仓库根加进 path，否则 bare 模式找不到 src 包
    code = (
        "import sys, os\n"
        f"sys.path.insert(0, {str(REPO_ROOT)!r})\n"
        "import streamlit as st\n"
        "from src.ui.views.overview import _render_inventory_result\n"
        "result = __RESULT__\n"
        "_render_inventory_result(result)\n"
    )

    script = code.replace("__RESULT__", repr(result))
    at = AppTest.from_string(script, default_timeout=90)
    at.run()
    assert not at.exception, f"渲染抛异常：{[e.value for e in at.exception]}"
    return [w.value for w in at.warning]


class TestMileageMismatchWarning:
    def test_warning_shown_when_mileage_deviates(self):
        """偏离 31.2%（顺丰型：实际 105000 vs 参考 80000）必须出警示。"""
        warns = _render_warnings(_result(31.2))
        joined = "\n".join(warns)
        assert warns, "里程偏离 +31.2% 时未出现任何口径警示"
        assert "口径提示" in joined
        assert "31.2%" in joined
        # 必须说清后果，而不只是报个数字
        assert "高估" in joined
        assert "活动水平差异" in joined

    def test_no_warning_when_mileage_matches(self):
        """里程与参考一致时不得打扰用户。"""
        warns = _render_warnings(_result(0.0))
        joined = "\n".join(warns)
        assert "口径提示" not in joined, "口径一致时不应出现口径警示"

    def test_threshold_boundary(self):
        """阈值是 5%：4.9 不提示，5.0 提示。"""
        below = "\n".join(_render_warnings(_result(4.9)))
        assert "口径提示" not in below

        at_threshold = "\n".join(_render_warnings(_result(5.0)))
        assert "口径提示" in at_threshold

    def test_negative_deviation_also_warns(self):
        """实际里程低于参考值同样会扭曲差额（低估），也要提示。"""
        joined = "\n".join(_render_warnings(_result(-18.0)))
        assert "口径提示" in joined
        assert "-18.0%" in joined

    def test_missing_field_does_not_crash(self):
        """老版本 API 响应没有这个字段时，页面不能崩。"""
        result = _result(0.0)
        del result["carbon_budget"]["活动水平偏离_pct"]
        warns = _render_warnings(result)
        assert "口径提示" not in "\n".join(warns)


class TestComputeActivityMismatch:
    """compute_activity_mismatch 是这套警示的数据源，单独验证其口径。"""

    def test_uses_activity_weighting_not_simple_average(self):
        from src.engine.calculator import VehicleGroupData

        groups = [
            # 100 辆重卡走 1.5 倍里程，1 辆轻卡走 0.1 倍里程
            VehicleGroupData("重型柴油货车", 100, 120000, 0.7),
            VehicleGroupData("轻型柴油货车", 1, 8000, 0.5),
        ]
        pct, note = compute_activity_mismatch(groups)
        # 按活动量加权应显著为正；简单平均会被那 1 辆车拉到接近 0
        assert pct > 20, f"活动量加权偏离应显著为正，实得 {pct:.1f}%"
        assert note, "偏离超 5% 却未生成说明文案"
        assert "参考" in note

    def test_consistent_fleet_gives_empty_note(self):
        from src.engine.calculator import VehicleGroupData

        # 正好等于参考里程 80000
        groups = [VehicleGroupData("重型柴油货车", 10, 80000, 0.8)]
        pct, note = compute_activity_mismatch(groups)
        assert abs(pct) < 1e-6, f"里程与参考完全一致时偏离应为 0，实得 {pct}"
        assert note == "", "偏离未超阈值时不应生成说明"
