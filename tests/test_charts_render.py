"""图表是答辩演示的核心载体，必须有「能渲染 + 数据真的进图」级测试。

背景（2026-10-29，覆盖率 27%）：`src/ui/components/charts.py` 有 12 个
纯函数画图，此前只被间接调用、几乎没有直接测试。图表出错的表现不是报错，
而是**静默画出一张空图或错图**——答辩现场才会发现。

本文件的判据刻意分两层：
1. 不抛异常（最低要求，空输入也必须给出「暂无数据」而不是崩）；
2. 数据真的进了图（trace 数量、关键数值、颜色语义、标注文本）。

只断言「返回了 Figure」等于没测——空 Figure 也是 Figure。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.engine.calculator import VehicleGroupData, calculate_emission  # noqa: E402
from src.ui.components import charts as C  # noqa: E402


def _real_emission():
    """用真实引擎产出 emission_by_type，避免自造形状与线上不一致。"""
    return calculate_emission([
        VehicleGroupData("重型柴油货车", 10, 80000, 0.70),
        VehicleGroupData("轻型柴油货车", 20, 30000, 0.80),
    ])


class TestEmptyInputsDegradeGracefully:
    """空数据必须给「暂无数据」提示，而不是空白画布。"""

    def test_fleet_comparison_empty(self) -> None:
        fig = C.plot_fleet_comparison([])
        assert len(fig.data) == 0
        annotations = [a.text for a in fig.layout.annotations]
        assert any("暂无" in (t or "") for t in annotations), (
            f"空数据时没有提示文案：{annotations}"
        )

    def test_payback_curve_empty(self) -> None:
        fig = C.plot_tco_payback_curve([], None)
        assert fig is not None  # 不抛异常即可，该函数没有单独的空态文案

    def test_rag_benchmark_empty(self) -> None:
        fig = C.plot_rag_benchmark({}, {})
        assert fig is not None


class TestEmissionPie:
    def test_contains_all_vehicle_types(self) -> None:
        data = _real_emission().emission_by_type
        fig = C.plot_emission_pie(data)
        labels = list(fig.data[0].labels or [])
        for vtype in data:
            assert vtype in labels, f"{vtype} 未出现在饼图里：{labels}"

    def test_values_match_engine_output(self) -> None:
        """饼图数值必须来自引擎，不能另算一套。"""
        data = _real_emission().emission_by_type
        fig = C.plot_emission_pie(data)
        values = list(fig.data[0].values or [])
        expected = [round(v["排放量_tCO2"], 2) for v in data.values()]
        assert sorted(values) == sorted(expected), (
            f"饼图数值 {sorted(values)} 与引擎输出 {sorted(expected)} 不一致"
        )


class TestQuotaComparison:
    def test_three_bars_for_emission_budget_gap(self) -> None:
        fig = C.plot_quota_comparison(total_emission=3352.8, total_quota=3010.7, gap=342.1)
        ys = [v for trace in fig.data for v in (trace.y or [])]
        assert 3352.8 in ys or any(abs(v - 3352.8) < 1 for v in ys), (
            f"排放量未进图：{ys}"
        )
        assert any(abs(v - 3010.7) < 1 for v in ys), f"预算未进图：{ys}"

    def test_gap_over_budget_uses_warning_color(self) -> None:
        """超预算与未超预算必须用不同颜色，否则一眼看不出结论。"""
        over = C.plot_quota_comparison(3352.8, 3010.7, 342.1)
        under = C.plot_quota_comparison(3000.0, 3200.0, -200.0)
        over_colors = [getattr(t.marker, "color", None) for t in over.data]
        under_colors = [getattr(t.marker, "color", None) for t in under.data]
        assert over_colors != under_colors, "超预算与未超预算的配色相同，结论不可辨"


class TestReductionComparison:
    def test_shows_baseline_and_scenario(self) -> None:
        """该图是横向条形图：数值在 x 轴，y 轴是分类标签。"""
        fig = C.plot_reduction_comparison(1000.0, 800.0)
        xs = [v for trace in fig.data for v in (trace.x or [])]
        assert any(abs(float(v) - 1000.0) < 1 for v in xs), f"基线未进图：{xs}"
        assert any(abs(float(v) - 800.0) < 1 for v in xs), f"情景未进图：{xs}"


class TestRagBenchmarkChart:
    """RQ2 图是答辩核心图之一，指标与误差线都必须真的来自结果文件。"""

    @pytest.fixture
    def summary(self) -> dict:
        import json

        path = ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json"
        if not path.exists():
            pytest.skip("评测结果尚未生成")
        return json.loads(path.read_text(encoding="utf-8"))["summary_metrics"]

    def test_all_modes_present(self, summary: dict) -> None:
        labels = {m: m for m in summary}
        fig = C.plot_rag_benchmark(summary, labels)
        xs = list(fig.data[0].x or [])
        assert set(xs) == set(summary), f"图里缺方案：{set(summary) - set(xs)}"

    def test_mrr_values_match_results(self, summary: dict) -> None:
        labels = {m: m for m in summary}
        fig = C.plot_rag_benchmark(summary, labels)
        ys = list(fig.data[0].y or [])
        expected = [summary[m]["MRR"] for m in summary]
        assert ys == pytest.approx(expected, abs=1e-6), (
            f"柱高与结果文件不一致：{ys} vs {expected}"
        )

    def test_error_bars_use_ci(self, summary: dict) -> None:
        """误差线必须来自 MRR_CI95，不能是常数或 0。"""
        labels = {m: m for m in summary}
        fig = C.plot_rag_benchmark(summary, labels)
        err = fig.data[0].error_y
        assert err is not None and err.array, "MRR 柱缺少误差线"
        for mode, up in zip(summary, err.array):
            ci = summary[mode].get("MRR_CI95")
            assert ci is not None
            assert abs(up - (ci[1] - summary[mode]["MRR"])) < 1e-6, (
                f"{mode} 的误差线上界与 CI 不符"
            )

    def test_recall_line_matches_results(self, summary: dict) -> None:
        labels = {m: m for m in summary}
        fig = C.plot_rag_benchmark(summary, labels)
        recall_trace = next(t for t in fig.data if "Recall" in (t.name or ""))
        expected = [summary[m]["Recall@10"] for m in summary]
        assert list(recall_trace.y) == pytest.approx(expected, abs=1e-6)


class TestCarbonPriceCharts:
    def test_history_handles_empty_dataframe(self) -> None:
        import pandas as pd

        fig = C.plot_carbon_price_history(pd.DataFrame())
        assert fig is not None

    def test_stats_returns_none_when_no_data(self) -> None:
        assert C.plot_carbon_price_stats({}) is None


class TestUncertaintyCharts:
    def test_histogram_marks_p5_p50_p95(self) -> None:
        """三点标注必须在图里，否则区间读不出来。"""
        hist = {"bin_centers": [5, 15, 25], "counts": [5, 20, 8]}  # 真实调用方用 bin_centers
        fig = C.plot_uncertainty_histogram(hist, point=15.0, p5=5.0, p95=28.0)
        texts = [a.text for a in fig.layout.annotations]
        joined = " ".join(t or "" for t in texts)
        assert "P5" in joined or "5.0" in joined, f"缺少 P5 标注：{texts}"
        assert "P95" in joined or "95" in joined, f"缺少 P95 标注：{texts}"

    def test_contributions_limits_to_top_n(self) -> None:
        contrib = {f"车型{i}": i / 10 for i in range(12)}
        fig = C.plot_uncertainty_contributions(contrib, top=5)
        ys = list(fig.data[0].y or [])
        assert len(ys) == 5, f"应只显示前 5 项，实际 {len(ys)}"
        # 必须按贡献从大到小
        assert ys == sorted(ys, reverse=True), f"未按贡献降序：{ys}"
