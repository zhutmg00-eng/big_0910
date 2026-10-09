#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成论文与图表共用的派生指标台账：docs/derived_metrics.json

用途：把论文正文、图 1~图 6 中出现的每一个关键数字，统一从仓库既有数据/代码派生一次，
避免"论文数字"与"脚本输出"漂移。任何修订后重跑本脚本即可刷新全部数字。

派生来源（全部为仓库内既有文件，不引入外部数据）：
- data/raw/real_fleets/benchmark_fleets.json   车队基准与能源台账
- data/raw/carbon_price_history.csv             全国碳市场碳价序列
- src/engine/*                                  计算/TCO/Scope2 引擎参数
- scripts/sensitivity_analysis.py 的扫描口径    满载率 × 里程 网格

用法（仓库根目录）：python scripts/gen_derived_metrics.py
"""
import json
import statistics
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.calculator import (  # noqa: E402
    VehicleGroupData,
    calculate_emission,
    calculate_load_adjustment,
)
from src.engine.carbon_price import (  # noqa: E402
    calculate_price_stats,
    estimate_compliance_cost,
    load_carbon_price_data,
)
from src.engine.emission_factors import get_all_factors  # noqa: E402
from src.engine.indirect_emission import (  # noqa: E402
    GRID_EMISSION_FACTORS,
    VEHICLE_ENERGY_SPECS,
)
from src.engine.tco import (  # noqa: E402
    TCOEconomicParameters,
    calculate_single_vehicle_tco,
    get_tco_benchmark,
)

OUT = PROJECT_ROOT / "docs" / "derived_metrics.json"
FLEET_JSON = PROJECT_ROOT / "data" / "raw" / "real_fleets" / "benchmark_fleets.json"

PROVINCES = [k for k in GRID_EMISSION_FACTORS if k not in
             ("全国平均", "全国平均(扣除非化石)", "全国化石电力",
              "华北区域", "东北区域", "华东区域", "华中区域", "西北区域", "南方区域", "西南区域")]

HEAVY = {"ef_ice_kg_per_km": 0.877, "kwh_per_100km": 150.0}
LIGHT = {"ef_ice_kg_per_km": 0.374, "kwh_per_100km": 35.0}


def payload_of(vehicle_type: str) -> float:
    if "重型" in vehicle_type or "半挂" in vehicle_type:
        return VEHICLE_ENERGY_SPECS["重型柴油货车"]["rated_payload_t"]
    if "中型" in vehicle_type:
        return VEHICLE_ENERGY_SPECS["中型柴油货车"]["rated_payload_t"]
    if "轻型" in vehicle_type:
        return VEHICLE_ENERGY_SPECS["轻型柴油货车"]["rated_payload_t"]
    if "微型" in vehicle_type:
        return VEHICLE_ENERGY_SPECS["微型汽油货车"]["rated_payload_t"]
    return VEHICLE_ENERGY_SPECS["新能源物流车"]["rated_payload_t"]


def main() -> dict:
    data = json.loads(FLEET_JSON.read_text(encoding="utf-8"))
    conv = data["metadata"]["emission_conversion_factors"]
    kg = {
        "柴油": conv["diesel_kg_co2_per_liter"],
        "汽油": conv["gasoline_kg_co2_per_liter"],
        "LNG": conv["lng_kg_co2_per_kg"],
    }
    factors = get_all_factors()

    def e_fuel_of(bench) -> float:
        led = bench["real_energy_ledger"]
        return round((led["diesel_liters"] * kg["柴油"] + led["gasoline_liters"] * kg["汽油"]
                      + led["lng_kg"] * kg["LNG"]) / 1000.0, 2)

    def e_model_of(bench, load_delta=0.0, km_scale=1.0, with_lf=True) -> float:
        groups = []
        for v in bench["fleet_input"]:
            eff_lf = v["load_factor"] if with_lf else 0.75
            groups.append(VehicleGroupData(
                vehicle_type=v["vehicle_type"],
                count=v["count"],
                annual_km=v["annual_km"] * km_scale,
                load_factor=max(0.0, min(1.0, eff_lf + load_delta)),
            ))
        return calculate_emission(groups).total_emission_t

    # ---------- A. 车队基准 ----------
    cases = []
    for b in data["benchmarks"]:
        ev = sum(v["count"] for v in b["fleet_input"] if v["vehicle_type"] == "新能源物流车")
        ice = sum(v["count"] for v in b["fleet_input"] if v["vehicle_type"] != "新能源物流车")
        e_model = e_model_of(b)
        e_nolf = e_model_of(b, with_lf=False)
        e_fuel = e_fuel_of(b)
        tkm = sum(v["count"] * v["annual_km"] * payload_of(v["vehicle_type"]) * v["load_factor"]
                  for v in b["fleet_input"])
        cases.append({
            "id": b["benchmark_id"],
            "company": b["company_name"],
            "scenario": b["scenario"],
            "vehicles_total": ice + ev,
            "vehicles_ice": ice,
            "vehicles_ev": ev,
            "e_model_tco2": e_model,
            "e_model_no_lf_tco2": e_nolf,
            "e_fuel_tco2": e_fuel,
            "e_reported_tco2": b["reported_scope1_tco2e"],
            "rel_err_pct": round((e_model - e_fuel) / e_fuel * 100, 2),
            "rel_err_no_lf_pct": round((e_nolf - e_fuel) / e_fuel * 100, 2),
            "load_factor_contribution_tco2": round(e_model - e_nolf, 2),
            "turnover_wan_tkm": round(tkm / 10000.0, 1),
            "intensity_g_per_tkm": round(e_model * 100 / (tkm / 10000.0), 2),
            "reported_scope1_tco2": b["reported_scope1_tco2e"],
        })

    errs = [abs(c["rel_err_pct"]) for c in cases]
    wts = [c["e_fuel_tco2"] for c in cases]
    errs_nolf = [abs(c["rel_err_no_lf_pct"]) for c in cases]
    mape = {
        "n_cases": len(cases),
        "equal_weight_pct": round(sum(errs) / len(errs), 2),
        "emission_weight_pct": round(sum(e * w for e, w in zip(errs, wts)) / sum(wts), 2),
        "pooled_pct": round(abs(sum(c["e_model_tco2"] for c in cases)
                                - sum(wts)) / sum(wts) * 100, 2),
        "equal_weight_no_lf_pct": round(sum(errs_nolf) / len(errs_nolf), 2),
        "vehicles_total": sum(c["vehicles_total"] for c in cases),
        "vehicles_ice": sum(c["vehicles_ice"] for c in cases),
        "vehicles_ev": sum(c["vehicles_ev"] for c in cases),
        "min_pct": round(min(errs), 2),
        "max_pct": round(max(errs), 2),
        "sum_e_model": round(sum(c["e_model_tco2"] for c in cases), 2),
        "sum_e_fuel": round(sum(wts), 2),
        "sum_load_factor_contribution": round(sum(c["load_factor_contribution_tco2"] for c in cases), 2),
    }

    # ---------- B. 参数扰动网格 ----------
    load_deltas = [-0.30, -0.25, -0.20, -0.15, -0.10, -0.05, 0.0, 0.05, 0.10, 0.15]
    km_scales = [0.8, 0.9, 1.0, 1.1, 1.2]
    grid = {}
    flat = []
    for ld in load_deltas:
        for ks in km_scales:
            errs_ = []
            for b in data["benchmarks"]:
                em = e_model_of(b, load_delta=ld, km_scale=ks)
                ef = e_fuel_of(b)
                errs_.append(abs(em - ef) / ef * 100)
            v = round(sum(errs_) / len(errs_), 2)
            grid[f"{ld:+.2f}|{ks:.1f}"] = v
            flat.append(v)
    sub_l = [-0.30, -0.15, 0.0, 0.10, 0.15]
    grid5 = [[grid[f"{ld:+.2f}|{ks:.1f}"] for ld in sub_l] for ks in km_scales]
    sensitivity = {
        "grid": grid,
        "grid_5x5": grid5,
        "row_labels_km_scale": km_scales,
        "col_labels_load_delta": sub_l,
        "min_pct": min(flat), "max_pct": max(flat),
        "median_pct": round(statistics.median(flat), 2),
        "n": len(flat),
        "over10": sum(1 for v in flat if v > 10.0),
        "mileage_effect_pp": round(grid["+0.00|1.2"] - grid["+0.00|1.0"], 2),
        "load_effect_pp": round(grid["+0.15|1.0"] - grid["-0.30|1.0"], 2),
    }

    # ---------- C. 电网与判据 ----------
    def net_pct(ef_ice, kwh_per_100km, factor):
        ev = kwh_per_100km / 100.0 * factor
        return round((ef_ice - ev) / ef_ice * 100, 2), round(ev, 4)

    grid_net = {}
    for p in PROVINCES:
        f = GRID_EMISSION_FACTORS[p]
        hp, hev = net_pct(HEAVY["ef_ice_kg_per_km"], HEAVY["kwh_per_100km"], f)
        lp, lev = net_pct(LIGHT["ef_ice_kg_per_km"], LIGHT["kwh_per_100km"], f)
        grid_net[p] = {
            "factor": f,
            "heavy_scope2_t_per_km": hev, "heavy_net_pct": hp,
            "light_scope2_t_per_km": lev, "light_net_pct": lp,
        }
    heavy_thr = round(100 * HEAVY["ef_ice_kg_per_km"] / HEAVY["kwh_per_100km"], 4)
    light_thr = round(100 * LIGHT["ef_ice_kg_per_km"] / LIGHT["kwh_per_100km"], 4)
    grid_metrics = {
        "n_provinces": len(PROVINCES),
        "province_order": sorted(PROVINCES, key=lambda p: GRID_EMISSION_FACTORS[p]),
        "province_factors": {p: GRID_EMISSION_FACTORS[p] for p in PROVINCES},
        "region_factors": {k: v for k, v in GRID_EMISSION_FACTORS.items() if k.endswith("区域")},
        "national": {
            "average": GRID_EMISSION_FACTORS["全国平均"],
            "non_fossil_excluded": GRID_EMISSION_FACTORS["全国平均(扣除非化石)"],
            "fossil_only": GRID_EMISSION_FACTORS["全国化石电力"],
        },
        "heavy": {
            **HEAVY,
            "threshold_kg_per_kwh": heavy_thr,
            "regions_above_threshold": sorted(
                [p for p in PROVINCES if GRID_EMISSION_FACTORS[p] > heavy_thr],
                key=lambda p: -GRID_EMISSION_FACTORS[p]),
            "threshold_range_kwh_per_100km_140_165": [
                round(100 * 0.877 / 165.0, 4), round(100 * 0.877 / 140.0, 4)],
            "threshold_range_with_ef_pm10pct": [
                round(100 * 0.877 * 0.9 / 165.0, 4), round(100 * 0.877 * 1.1 / 140.0, 4)],
        },
        "light": {
            **LIGHT,
            "threshold_kg_per_kwh": light_thr,
            "threshold_at_40kwh": round(100 * 0.374 / 40.0, 4),
            "min_net_pct_across_provinces": min(v["light_net_pct"] for v in grid_net.values()),
        },
        "by_province": grid_net,
    }

    # ---------- D. 碳价 ----------
    df = load_carbon_price_data()
    stats = calculate_price_stats(df)
    price_metrics = {
        "stats_recent_90d": stats,
        "rows_total": int(len(df)),
        "rows_real": int((df["数据来源"] == "真实数据").sum()),
        "rows_interpolated": int((df["数据来源"] != "真实数据").sum()),
        "date_min": str(df["日期"].min().date()),
        "date_max": str(df["日期"].max().date()),
        "synthetic_share_pct": round((df["数据来源"] != "真实数据").mean() * 100, 1),
    }

    # ---------- E. 贯穿案例 Fleet-Alpha ----------
    alpha = [VehicleGroupData("重型柴油货车", 100, 100000, 0.70),
             VehicleGroupData("轻型柴油货车", 50, 35000, 0.65)]
    res = calculate_emission(alpha)
    pkt = (100 * 100000 * 25.0 * 0.70 + 50 * 35000 * 2.0 * 0.65) / 10000.0
    b_heavy = round(0.877 * 80000 / 1000.0 * 0.90, 4)
    b_light = round(0.374 * 30000 / 1000.0 * 0.90, 4)
    b_total = round(100 * b_heavy + 50 * b_light, 2)
    gap = round(res.total_emission_t - b_total, 2)
    e_no_lf = round(sum(g.count * g.annual_km * factors[g.vehicle_type]["co2_kg_per_km"] / 1000.0
                        for g in alpha), 2)
    alpha_metrics = {
        "e_direct_tco2": res.total_emission_t,
        "e_direct_no_lf_tco2": e_no_lf,
        "lf_contribution_tco2": round(res.total_emission_t - e_no_lf, 2),
        "per_vehicle_heavy_tco2": round(100000 * 0.877 * calculate_load_adjustment(0.70) / 1000.0, 3),
        "per_vehicle_light_tco2": round(35000 * 0.374 * calculate_load_adjustment(0.65) / 1000.0, 3),
        "turnover_wan_tkm": pkt,
        "intensity_g_per_tkm": round(res.total_emission_t * 100 / pkt, 2),
        "budget_heavy_per_vehicle": b_heavy,
        "budget_light_per_vehicle": b_light,
        "budget_total_tco2": b_total,
        "gap_tco2": gap,
        "cost_scenario": estimate_compliance_cost(gap, df),
    }

    # ---------- F. TCO ----------
    def tco_case(vehicle_type, count, km, load_factor, label, params):
        from src.engine.reduction import REPLACEMENT_MAP
        ef_old = REPLACEMENT_MAP.get(vehicle_type, (None, 0.877))[1]
        annual_red = count * km * ef_old * calculate_load_adjustment(load_factor) / 1000.0
        r = calculate_single_vehicle_tco(vehicle_type, count, km, annual_red, econ_params=params)
        return {
            "label": label,
            "vehicle_type": vehicle_type,
            "count": count,
            "annual_km": km,
            "delta_capex_per_vehicle_wan": round(r.delta_capex_per_vehicle_yuan / 10000.0, 3),
            "delta_capex_total_wan": round(r.delta_capex_total_yuan / 10000.0, 3),
            "annual_opex_saving_per_vehicle_wan": round(r.annual_opex_saving_total_yuan / count / 10000.0, 3),
            "payback_years": round(r.payback_period_years, 2) if r.payback_period_years else None,
            "annual_co2_reduction_t": round(r.annual_co2_reduction_t, 2),
            "mac_yuan_per_tco2e": round(r.mac_yuan_per_tco2e, 2) if r.mac_yuan_per_tco2e is not None else None,
            "lifespan_years": params.lifespan_years,
            "is_baas": params.is_baas_mode,
        }

    tco_metrics = {
        "benchmarks": {
            vt: {
                "ice_price_wan": get_tco_benchmark(vt).ice_vehicle_price_wan,
                "ev_price_wan": get_tco_benchmark(vt).ev_vehicle_price_wan,
                "charger_wan": get_tco_benchmark(vt).charger_cost_wan,
                "fuel_l_per_100km": get_tco_benchmark(vt).fuel_consumption_per_100km,
                "elec_kwh_per_100km": get_tco_benchmark(vt).electricity_consumption_per_100km,
                "maint_ice_yuan": get_tco_benchmark(vt).annual_maintenance_ice_yuan,
            } for vt in ("重型柴油货车", "轻型柴油货车")
        },
        "light_cases": [
            tco_case("轻型柴油货车", 20, 35000.0, 0.65, "purchase", TCOEconomicParameters(lifespan_years=5)),
            tco_case("轻型柴油货车", 20, 35000.0, 0.65, "baas", TCOEconomicParameters(
                lifespan_years=5, is_baas_mode=True, baas_chassis_discount_wan=5.0,
                baas_annual_battery_rental_yuan=13500.0)),
        ],
        "heavy_cases": [
            tco_case("重型柴油货车", 20, 100000.0, 0.70, "purchase", TCOEconomicParameters(lifespan_years=5)),
            tco_case("重型柴油货车", 20, 100000.0, 0.70, "baas", TCOEconomicParameters(
                lifespan_years=5, is_baas_mode=True, baas_chassis_discount_wan=20.0,
                baas_annual_battery_rental_yuan=45000.0)),
        ],
    }

    # ---------- G. RAG 检索指标（直接取自既有实验结果文件） ----------
    rag_path = PROJECT_ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json"
    rag_metrics = {}
    if rag_path.exists():
        raw = json.loads(rag_path.read_text(encoding="utf-8"))
        rag_metrics["source_file"] = str(rag_path.relative_to(PROJECT_ROOT)).replace("\\", "/")
        rag_metrics["raw_keys"] = sorted(raw.keys()) if isinstance(raw, dict) else "list"
        rag_metrics["payload"] = raw if isinstance(raw, dict) else {"items": raw}

    out = {
        "generated_by": "scripts/gen_derived_metrics.py",
        "note": "本文件是论文与图表的唯一数字台账；修改引擎参数后需重跑本脚本与 build_academic_pdf.py。",
        "fleet_cases": cases,
        "mape": mape,
        "sensitivity": sensitivity,
        "grid": grid_metrics,
        "carbon_price": price_metrics,
        "fleet_alpha": alpha_metrics,
        "tco": tco_metrics,
        "rag": rag_metrics,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return out


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    m = main()
    print(f"written: {OUT}")
    print("MAPE:", m["mape"]["equal_weight_pct"], "(equal) /",
          m["mape"]["emission_weight_pct"], "(weighted)")
    print("vehicles:", m["mape"]["vehicles_total"],
          f"(ICE {m['mape']['vehicles_ice']} / EV {m['mape']['vehicles_ev']})")
    print("sensitivity:", m["sensitivity"]["min_pct"], "~", m["sensitivity"]["max_pct"],
          "median", m["sensitivity"]["median_pct"])
    print("heavy threshold:", m["grid"]["heavy"]["threshold_kg_per_kwh"],
          "| above:", m["grid"]["heavy"]["regions_above_threshold"])
    print("Fleet-Alpha:", m["fleet_alpha"]["e_direct_tco2"], "tCO2; gap",
          m["fleet_alpha"]["gap_tco2"], "tCO2; cost",
          m["fleet_alpha"]["cost_scenario"]["情景成本_参考价"], "CNY")
    for c in m["tco"]["light_cases"] + m["tco"]["heavy_cases"]:
        print("  TCO", c["vehicle_type"], c["label"], "capex/veh",
              c["delta_capex_per_vehicle_wan"], "wan; payback", c["payback_years"], "y")
