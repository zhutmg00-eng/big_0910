"""减排分析引擎测试"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engine.calculator import VehicleGroupData, calculate_emission
from src.engine.quota import estimate_quota_gap
from src.engine.reduction import (
    ReductionScenario,
    _build_scenario_fleet,
    _summarize_fleet,
    analyze_reduction_scenario,
    compare_scenarios,
    find_optimal_reduction,
)


class TestReductionEngine:
    @pytest.fixture
    def sample_fleet(self):
        return [
            VehicleGroupData(vehicle_type="重型柴油货车", count=50, annual_km=80000, load_factor=0.70),
            VehicleGroupData(vehicle_type="中型柴油货车", count=30, annual_km=50000, load_factor=0.75),
        ]

    def test_build_scenario_fleet_vehicle_count_preserved(self, sample_fleet):
        """情景车队总车辆数应与基线完全一致"""
        changes = {"替换为新能源物流车": 15}
        scenario_fleet = _build_scenario_fleet(sample_fleet, changes)
        total_scenario_vehicles = sum(g.count for g in scenario_fleet)
        total_base_vehicles = sum(g.count for g in sample_fleet)
        assert total_scenario_vehicles == total_base_vehicles == 80

        # 检查新能源车数量
        ev_count = sum(g.count for g in scenario_fleet if g.vehicle_type == "新能源物流车")
        assert ev_count == 15

    def test_analyze_reduction_scenario_positive_reduction(self, sample_fleet):
        """新能源替代应产生正向减排量与减排比例"""
        changes = {"替换为新能源物流车": 20}
        analysis = analyze_reduction_scenario(sample_fleet, changes)
        assert analysis.reduction_t > 0
        assert analysis.reduction_pct > 0
        assert analysis.scenario_emission < analysis.baseline_emission
        assert len(analysis.recommendations) > 0

    def test_analyze_reduction_load_factor_improvement(self, sample_fleet):
        """提升满载率应降低单位排放"""
        changes = {"提升满载率至85%": 50}
        analysis = analyze_reduction_scenario(sample_fleet, changes)
        assert analysis.reduction_t > 0
        assert analysis.scenario_emission < analysis.baseline_emission

    def test_compare_scenarios(self, sample_fleet):
        """多情景对比应按减排效果排序"""
        scenarios = [
            ReductionScenario(name="微量替代", description="替换5辆新能源", changes={"替换为新能源物流车": 5}),
            ReductionScenario(name="大量替代", description="替换30辆新能源", changes={"替换为新能源物流车": 30}),
        ]
        comparison = compare_scenarios(sample_fleet, scenarios)
        assert len(comparison.scenarios) == 2
        assert comparison.scenarios[0].reduction_t >= comparison.scenarios[1].reduction_t
        assert len(comparison.recommendations) > 0

    def test_find_optimal_reduction(self, sample_fleet):
        """最优减排求解应返回有效的推荐方案"""
        result = find_optimal_reduction(sample_fleet)
        assert len(result.scenarios) > 0
        assert result.scenarios[0].reduction_t > 0


class TestDuplicateGroupRegression:
    """回归：同车型多组输入时统计口径一致（2026-09-08 修复）

    根因：reduction 内曾用 {g.vehicle_type: g.count for g in fleet}
    dict 覆盖式统计，同车型分组（如用户分两行输入 30+20 辆重型车）
    会丢组；排放按加总口径，预算基准却按覆盖后少数车辆计，导致
    预算差额与情景成本全部失真。
    """

    @staticmethod
    def _split_fleet():
        # 真实场景：用户分两行输入同车型，满载率可能不同
        return [
            VehicleGroupData(vehicle_type="重型柴油货车", count=30, annual_km=80000, load_factor=0.70),
            VehicleGroupData(vehicle_type="重型柴油货车", count=20, annual_km=80000, load_factor=0.75),
        ]

    @staticmethod
    def _split_fleet_same_load():
        # 对照场景：同车型分组但满载率一致（可无损合并）
        return [
            VehicleGroupData(vehicle_type="重型柴油货车", count=30, annual_km=80000, load_factor=0.75),
            VehicleGroupData(vehicle_type="重型柴油货车", count=20, annual_km=80000, load_factor=0.75),
        ]

    @staticmethod
    def _merged_fleet():
        return [VehicleGroupData(vehicle_type="重型柴油货车", count=50, annual_km=80000, load_factor=0.75)]

    def test_summarize_fleet_merges_duplicate_groups(self):
        """同车型多组应合并为 50 辆（此前覆盖丢组只计 20）"""
        summary = _summarize_fleet(self._split_fleet())
        assert summary["重型柴油货车"] == 50

    def test_quota_gap_split_equals_merged(self):
        """分两组输入与合并单组输入的模拟预算基准必须一致（不丢组）"""
        split_fleet = self._split_fleet()
        merged_fleet = self._merged_fleet()

        split_gap = estimate_quota_gap(
            calculate_emission(split_fleet).total_emission_t, _summarize_fleet(split_fleet)
        )
        merged_gap = estimate_quota_gap(
            calculate_emission(merged_fleet).total_emission_t, _summarize_fleet(merged_fleet)
        )
        # 模拟预算基准只取决于车辆数与车型，与满载率无关 → 必须完全相等
        assert split_gap.total_quota_t == merged_gap.total_quota_t
        # 直接断言 50 辆重型车的基准：63.144 t/辆 × 50（防基准表变更误报，用相对断言）
        assert split_gap.total_quota_t > 0
        assert split_gap.total_quota_t == pytest.approx(63.144 * 50, rel=1e-6)

    def test_quota_gap_same_load_split_fully_equal(self):
        """同满载率分组输入与合并单组：排放、预算、差额全链路一致"""
        split_fleet = self._split_fleet_same_load()
        merged_fleet = self._merged_fleet()

        split_baseline = calculate_emission(split_fleet)
        merged_baseline = calculate_emission(merged_fleet)
        assert abs(split_baseline.total_emission_t - merged_baseline.total_emission_t) < 0.1

        split_gap = estimate_quota_gap(split_baseline.total_emission_t, _summarize_fleet(split_fleet))
        merged_gap = estimate_quota_gap(merged_baseline.total_emission_t, _summarize_fleet(merged_fleet))
        assert split_gap.total_quota_t == merged_gap.total_quota_t
        assert split_gap.gap_t == merged_gap.gap_t
        assert split_gap.gap_status == merged_gap.gap_status

    def test_analyze_reduction_split_equals_merged(self):
        """减排分析（同满载率分组 vs 合并输入）结果应完全一致"""
        changes = {"替换为新能源物流车": 10}
        split_analysis = analyze_reduction_scenario(self._split_fleet_same_load(), changes)
        merged_analysis = analyze_reduction_scenario(self._merged_fleet(), changes)
        assert split_analysis.reduction_t == merged_analysis.reduction_t
        assert split_analysis.cost_savings == merged_analysis.cost_savings

    def test_analyze_reduction_split_load_differs_no_crash_and_no_dup(self):
        """不同满载率分组输入：不丢组、不崩溃、新能源替换量精确"""
        changes = {"替换为新能源物流车": 10}
        analysis = analyze_reduction_scenario(self._split_fleet(), changes)
        # 10 辆替换的减排贡献：换掉的是 30 辆@0.7 组中的 10 辆（顺序消费）
        expected_reduction = 10 * 80000 * 0.877 * 1.0075 / 1000
        assert analysis.reduction_t == pytest.approx(expected_reduction, rel=1e-3)
        assert analysis.scenario_emission < analysis.baseline_emission

    def test_multi_measure_multi_type_combination_conservation(self):
        """多车型 + 多措施组合：车辆数与各措施替换量精确（防重复统计回归）"""
        fleet = [
            VehicleGroupData(vehicle_type="重型柴油货车", count=50, annual_km=80000, load_factor=0.70),
            VehicleGroupData(vehicle_type="中型柴油货车", count=30, annual_km=50000, load_factor=0.75),
            VehicleGroupData(vehicle_type="轻型柴油货车", count=20, annual_km=30000, load_factor=0.60),
        ]
        total_base = sum(g.count for g in fleet)
        scenario_fleet = _build_scenario_fleet(fleet, {
            "替换为新能源物流车": 20,
            "重型货车更换LNG": 10,
            "提升满载率至0.8": 40,
        })
        summary = _summarize_fleet(scenario_fleet)
        assert sum(g.count for g in scenario_fleet) == total_base == 100
        assert summary.get("新能源物流车", 0) == 20
        assert summary.get("LNG重型货车", 0) == 10
        assert summary.get("重型柴油货车", 0) == 20
        assert summary.get("中型柴油货车", 0) == 30
        assert summary.get("轻型柴油货车", 0) == 20
