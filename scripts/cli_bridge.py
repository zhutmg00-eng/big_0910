#!/usr/bin/env python3
"""DeepSeek Harness (dsh) CLI 桥接引擎。

提供无头（Headless）命令行 JSON 接口，供 dsh-plugin-carbon-asset 在未启动 FastAPI 服务时
作为本地子进程透明调用。
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from dataclasses import asdict
from pathlib import Path

# 确保在 Windows 与跨平台下输入输出均为 utf-8
if sys.stdout and hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
if sys.stderr and hasattr(sys.stderr, "buffer"):
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")

# 确保能正确导入项目源码模块
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

# 预先导入 main，避免 routes_compare 的循环引用
import src.api.main

from src.engine.calculator import VehicleGroupData, calculate_emission
from src.engine.carbon_price import estimate_compliance_cost, load_carbon_price_data
from src.engine.emission_factors import get_all_factors
from src.engine.quota import estimate_quota_gap
from src.engine.reduction import analyze_reduction_scenario
from src.engine.tco import (
    DEFAULT_TCO_BENCHMARKS,
    TCOEconomicParameters,
    VehicleTCOBenchmark,
    calculate_fleet_tco,
    calculate_single_vehicle_tco,
    get_tco_benchmark,
)
from src.engine.indirect_emission import (
    calculate_scope2_emission,
    calculate_turnover_and_intensity,
)


def handle_calculate(payload: dict) -> dict:
    company_name = payload.get("company_name", "示例物流企业")
    fleet_raw = payload.get("fleet", [])
    reduction_target = float(payload.get("scenario_reduction_target", 0.10))

    fleet = [
        VehicleGroupData(
            vehicle_type=v["vehicle_type"],
            count=int(v["count"]),
            annual_km=float(v["annual_km"]),
            load_factor=float(v.get("load_factor", 0.75)),
        )
        for v in fleet_raw
    ]

    baseline = calculate_emission(fleet)
    fleet_summary = {}
    for v in fleet_raw:
        vtype = v["vehicle_type"]
        fleet_summary[vtype] = fleet_summary.get(vtype, 0) + int(v["count"])

    gap = estimate_quota_gap(
        baseline.total_emission_t,
        fleet_summary,
        reduction_target=reduction_target,
    )

    price_df = load_carbon_price_data()
    cost = estimate_compliance_cost(gap.gap_t, price_df)

    return {
        "company_name": company_name,
        "total_emission_t": baseline.total_emission_t,
        "total_vehicles": baseline.total_vehicles,
        "emission_by_type": baseline.emission_by_type,
        "carbon_budget": {
            "模拟碳预算_t": gap.total_quota_t,
            "预算差额_t": gap.gap_t,
            "状态": gap.gap_status,
            "分车型预算": gap.quota_by_type,
            "情景减排目标": gap.reduction_target,
            "口径说明": "科研原型估算，不是法定配额或履约依据",
        },
        "scenario_cost": cost,
        "methodology_note": "当前仅核算车辆直接运营排放；新能源物流车的购电间接排放及全生命周期排放未计入。",
    }


def handle_tco(payload: dict) -> dict:
    vehicle_type = payload["vehicle_type"]
    replace_count = int(payload.get("replace_count", 1))
    annual_km = float(payload.get("annual_km", 80000.0))
    annual_co2_reduction_t = float(payload.get("annual_co2_reduction_t", 0.0))

    spec = get_tco_benchmark(vehicle_type)
    if spec is None:
        raise ValueError(f"不支持的车型: {vehicle_type}")

    if payload.get("ev_vehicle_price_wan") is not None:
        spec = VehicleTCOBenchmark(
            ice_vehicle_price_wan=spec.ice_vehicle_price_wan,
            ev_vehicle_price_wan=float(payload["ev_vehicle_price_wan"]),
            charger_cost_wan=spec.charger_cost_wan,
            fuel_consumption_per_100km=spec.fuel_consumption_per_100km,
            electricity_consumption_per_100km=spec.electricity_consumption_per_100km,
            fuel_type=spec.fuel_type,
            annual_maintenance_ice_yuan=spec.annual_maintenance_ice_yuan,
            maintenance_saving_ratio=spec.maintenance_saving_ratio,
        )

    econ = TCOEconomicParameters(
        diesel_price_yuan_per_l=float(payload.get("diesel_price_yuan_per_l", 7.50)),
        electricity_price_yuan_per_kwh=float(payload.get("electricity_price_yuan_per_kwh", 0.80)),
        lifespan_years=int(payload.get("lifespan_years", 5)),
    )

    res = calculate_single_vehicle_tco(
        vehicle_type=vehicle_type,
        replace_count=replace_count,
        annual_km=annual_km,
        annual_co2_reduction_t=annual_co2_reduction_t,
        custom_benchmark=spec,
        econ_params=econ,
    )
    return asdict(res)


def handle_reduction(payload: dict) -> dict:
    fleet_raw = payload.get("baseline_fleet", [])
    changes = payload.get("changes", {})
    budget_target = float(payload.get("budget_reduction_target", 0.10))

    baseline_fleet = [
        VehicleGroupData(
            vehicle_type=item["vehicle_type"],
            count=int(item["count"]),
            annual_km=float(item["annual_km"]),
            load_factor=float(item.get("load_factor", 0.75)),
        )
        for item in fleet_raw
    ]

    analysis = analyze_reduction_scenario(
        baseline_fleet=baseline_fleet,
        changes=changes,
        budget_reduction_target=budget_target,
    )
    return analysis.to_dict()


def handle_policy(payload: dict) -> dict:
    from src.rag import PolicyAdvisor

    question = payload.get("question", "")
    carbon_profile = payload.get("carbon_profile", {})
    advisor = PolicyAdvisor()
    return advisor.ask(question, carbon_profile)


def handle_compare(payload: dict) -> dict:
    import asyncio
    from src.api.routes_compare import CompareFleetInput, CompareRequest, compare_enterprises

    companies_raw = payload.get("companies", [])
    req = CompareRequest(
        companies=[
            CompareFleetInput(
                company_name=c["company_name"],
                fleet=c["fleet"],
                scenario_reduction_target=float(c.get("scenario_reduction_target", 0.10)),
            )
            for c in companies_raw
        ]
    )
    resp = asyncio.run(compare_enterprises(req))
    return resp.model_dump()


def handle_vehicle_types() -> dict:
    factors = get_all_factors()
    return {
        "vehicle_types": [
            {
                "name": name,
                "fuel_type": data["fuel_type"],
                "co2_kg_per_km": data["co2_kg_per_km"],
                "avg_annual_km": data["avg_annual_km"],
            }
            for name, data in factors.items()
        ],
        "tco_benchmarks": {k: asdict(v) for k, v in DEFAULT_TCO_BENCHMARKS.items()},
    }


def handle_turnover(payload: dict) -> dict:
    fleet_raw = payload.get("fleet", [])
    region = payload.get("region", "全国")
    green_ratio = float(payload.get("green_electricity_ratio", 0.0))
    fleet = [
        VehicleGroupData(
            vehicle_type=v["vehicle_type"],
            count=int(v["count"]),
            annual_km=float(v["annual_km"]),
            load_factor=float(v.get("load_factor", 0.75)),
        )
        for v in fleet_raw
    ]
    scope2_res = calculate_scope2_emission(fleet, region, green_ratio)
    turnover_res = calculate_turnover_and_intensity(fleet, scope2_emission_t=scope2_res.scope2_emission_t)
    return {
        "scope2": asdict(scope2_res),
        "turnover_and_intensity": asdict(turnover_res),
    }


def main():
    parser = argparse.ArgumentParser(description="DeepSeek Harness CLI Bridge for Carbon Asset Assistant")
    parser.add_argument("command", choices=["calculate", "tco", "reduction", "policy", "compare", "vehicle-types", "turnover"])
    parser.add_argument("--json", type=str, help="JSON input payload (or via stdin)")

    args = parser.parse_args()

    payload = {}
    if args.json:
        payload = json.loads(args.json)
    elif not sys.stdin.isatty():
        stdin_content = sys.stdin.read().strip()
        if stdin_content:
            payload = json.loads(stdin_content)

    try:
        if args.command == "calculate":
            result = handle_calculate(payload)
        elif args.command == "tco":
            result = handle_tco(payload)
        elif args.command == "reduction":
            result = handle_reduction(payload)
        elif args.command == "policy":
            result = handle_policy(payload)
        elif args.command == "compare":
            result = handle_compare(payload)
        elif args.command == "vehicle-types":
            result = handle_vehicle_types()
        elif args.command == "turnover":
            result = handle_turnover(payload)
        else:
            raise ValueError(f"未知子命令: {args.command}")

        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        err_output = {"error": str(e), "type": type(e).__name__}
        print(json.dumps(err_output, ensure_ascii=False), file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
