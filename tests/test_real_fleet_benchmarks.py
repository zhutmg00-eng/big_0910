# -*- coding: utf-8 -*-
"""真实车队基准数据与核算模型自动化测试。

测试目标：
1. 验证 data/raw/real_fleets/ 中的基准数据文件格式与结构完整性；
2. 验证基准车队数据均能被计算引擎成功处理，无未识别车型或异常；
3. 验证活动水平测算值与能源台账核算值的相对误差在合理理论边界内 (|MAPE| < 10%)；
4. 验证满载率调整函数对低满载率车队产生正确的上浮修正效果。
"""

import json
from pathlib import Path
import pytest

from src.engine.calculator import (
    calculate_emission,
    VehicleGroupData,
)
from src.engine.emission_factors import get_emission_factor

BENCHMARK_DIR = Path(__file__).resolve().parent.parent / "data" / "raw" / "real_fleets"
BENCHMARK_JSON = BENCHMARK_DIR / "benchmark_fleets.json"
BENCHMARK_CSV = BENCHMARK_DIR / "benchmark_fleets.csv"


@pytest.fixture(scope="module")
def benchmark_data():
    assert BENCHMARK_JSON.exists(), f"找不到真实基准数据文件: {BENCHMARK_JSON}"
    with open(BENCHMARK_JSON, "r", encoding="utf-8") as f:
        return json.load(f)


def test_benchmark_files_exist():
    """验证基准数据集文件均存在"""
    assert BENCHMARK_JSON.exists()
    assert BENCHMARK_CSV.exists()
    assert (BENCHMARK_DIR / "sources_and_methodology.md").exists()


def test_benchmark_structure(benchmark_data):
    """验证基准数据 schema 结构完整性"""
    assert "metadata" in benchmark_data
    assert "benchmarks" in benchmark_data
    benchmarks = benchmark_data["benchmarks"]
    assert len(benchmarks) >= 4, "基准车队案例数量应至少为4组"

    required_fields = [
        "benchmark_id",
        "company_name",
        "scenario",
        "source_document",
        "fleet_input",
        "real_energy_ledger",
        "derived_baseline_from_ledger_tco2e",
    ]
    for b in benchmarks:
        for field in required_fields:
            assert field in b, f"案例 {b.get('benchmark_id')} 缺少字段 {field}"
        assert len(b["fleet_input"]) > 0
        assert b["derived_baseline_from_ledger_tco2e"] > 0


def test_metadata_declares_field_semantics(benchmark_data):
    """字段语义必须显式声明为「复算值」，防止被当成企业原始披露值引用。"""
    meta = benchmark_data["metadata"]
    assert "field_semantics" in meta, "metadata 必须包含 field_semantics 声明"
    semantics = " ".join(str(v) for v in meta["field_semantics"].values())
    assert "非企业原始披露值" in semantics, "必须显式声明该字段不是企业原始披露值"


def test_reported_scope1_label_not_used_for_values(benchmark_data):
    """禁止重新引入被误读为「企业披露值」的字段名。"""
    for b in benchmark_data["benchmarks"]:
        assert "reported_scope1_tco2e" not in b, (
            f"案例 {b['benchmark_id']} 仍使用 reported_scope1_tco2e，会被误读为企业披露值"
        )


def test_grid_factor_single_source_of_truth(benchmark_data):
    """电网因子必须与引擎中的官方全国平均值一致，禁止两套并存。"""
    from src.engine.indirect_emission import GRID_EMISSION_FACTORS

    conv = benchmark_data["metadata"]["emission_conversion_factors"]
    official = conv["official_national_grid_kg_co2_per_kwh"]
    assert official == GRID_EMISSION_FACTORS["全国平均"], (
        f"数据集官方电网因子 {official} 与引擎 {GRID_EMISSION_FACTORS['全国平均']} 不一致"
    )
    assert conv["grid_electricity_kg_co2_per_kwh"] != official, (
        "历史沿用值应与官方值明确区分，不应相同"
    )


def test_all_fleet_vehicle_types_supported(benchmark_data):
    """验证所有真实车队用到的车型都在支持列表中"""
    for b in benchmark_data["benchmarks"]:
        for v in b["fleet_input"]:
            vtype = v["vehicle_type"]
            factor = get_emission_factor(vtype)
            assert factor is not None, f"案例 {b['benchmark_id']} 包含不支持的车型: {vtype}"
            assert factor["co2_kg_per_km"] >= 0


def test_real_fleet_calculation_accuracy(benchmark_data):
    """验证模型测算值与能源台账基准的相对误差在合理阈值以内 (全样本 MAPE < 10%, 单样本 < 15%)"""
    conv = benchmark_data["metadata"]["emission_conversion_factors"]
    diesel_factor = conv.get("diesel_kg_co2_per_liter", 2.730)
    gasoline_factor = conv.get("gasoline_kg_co2_per_liter", 2.310)
    lng_factor = conv.get("lng_kg_co2_per_kg", 2.690)

    relative_errors = []

    for b in benchmark_data["benchmarks"]:
        fleet_data = [
            VehicleGroupData(
                vehicle_type=v["vehicle_type"],
                count=v["count"],
                annual_km=v["annual_km"],
                load_factor=v.get("load_factor", 0.75),
            )
            for v in b["fleet_input"]
        ]
        result = calculate_emission(fleet_data)
        e_model = result.total_emission_t

        ledger = b["real_energy_ledger"]
        e_fuel = (
            ledger.get("diesel_liters", 0) * diesel_factor
            + ledger.get("gasoline_liters", 0) * gasoline_factor
            + ledger.get("lng_kg", 0) * lng_factor
        ) / 1000.0

        assert e_fuel > 0
        rel_error = abs((e_model - e_fuel) / e_fuel) * 100.0
        relative_errors.append(rel_error)

        # 单案例绝对相对误差不应超过 15%
        assert rel_error < 15.0, (
            f"案例 {b['benchmark_id']} 相对误差过大: {rel_error:.2f}% "
            f"(Model: {e_model:.2f}, Fuel: {e_fuel:.2f})"
        )

    # 全样本平均绝对百分比误差 (MAPE) 不超过 8%
    mape = sum(relative_errors) / len(relative_errors)
    assert mape < 8.0, f"真实基准整体 MAPE 过大: {mape:.2f}%"


def test_load_factor_adjustment_effect(benchmark_data):
    """验证冷链城配等低满载率车队受满载率调整系数影响后排放上浮"""
    cold_chain_b = next(
        (b for b in benchmark_data["benchmarks"] if "Coldchain" in b["benchmark_id"]),
        None,
    )
    assert cold_chain_b is not None

    fleet_with_adj = [
        VehicleGroupData(
            vehicle_type=v["vehicle_type"],
            count=v["count"],
            annual_km=v["annual_km"],
            load_factor=v.get("load_factor", 0.75),
        )
        for v in cold_chain_b["fleet_input"]
    ]
    res_adj = calculate_emission(fleet_with_adj)

    # 如果所有满载率设为 0.75（不触发调整）
    fleet_without_adj = [
        VehicleGroupData(
            vehicle_type=v["vehicle_type"],
            count=v["count"],
            annual_km=v["annual_km"],
            load_factor=0.75,
        )
        for v in cold_chain_b["fleet_input"]
    ]
    res_no_adj = calculate_emission(fleet_without_adj)

    assert res_adj.total_emission_t > res_no_adj.total_emission_t
