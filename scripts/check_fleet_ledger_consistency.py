#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""车队台账一致性核验：模型活动参数与披露能耗之间的量级自洽性检查。

背景
----
`benchmark_fleets.json` 里的分车型年均里程与实载率，一部分来自公开统计锚定，一部分是
合理假设（见 `data/raw/real_fleets/sources_and_methodology.md` 附录 A）。企业 ESG 报告
通常只披露车队级燃料总量，不拆分车型。因此"车型构成 + 里程 + 因子"反算出的等效燃料量，
与披露燃料量之间会存在差异。

本脚本不做任何拟合或调参，只做两件事：
1. 逐案例、逐燃料计算"模型等效燃料量 / 披露燃料量"的比值（ratio）；
2. 反解使比值等于 1 所需的**同车型有效车辆数**，用于判断披露能耗能支撑多大范围的车队。

用法（仓库根目录）：
    python scripts/check_fleet_ledger_consistency.py
    python scripts/check_fleet_ledger_consistency.py --json   # 机器可读输出
"""
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.emission_factors import get_all_factors  # noqa: E402

FLEET_JSON = PROJECT_ROOT / "data" / "raw" / "real_fleets" / "benchmark_fleets.json"


def main() -> dict:
    data = json.loads(FLEET_JSON.read_text(encoding="utf-8"))
    conv = data["metadata"]["emission_conversion_factors"]
    kg_per_unit = {
        "柴油": conv["diesel_kg_co2_per_liter"],
        "汽油": conv["gasoline_kg_co2_per_liter"],
        "LNG": conv["lng_kg_co2_per_kg"],
    }
    factors = get_all_factors()
    out = {"conversion_factors": conv, "cases": []}

    for b in data["benchmarks"]:
        led = b["real_energy_ledger"]
        rows = []
        for v in b["fleet_input"]:
            ef = factors[v["vehicle_type"]]
            fuel = ef["fuel_type"]
            if fuel not in kg_per_unit:
                rows.append({**v, "fuel_type": fuel, "note": "电动车，无直接燃烧燃料"})
                continue
            vkm = v["count"] * v["annual_km"]
            co2_kg = vkm * ef["co2_kg_per_km"]
            rows.append({
                "vehicle_type": v["vehicle_type"],
                "count": v["count"],
                "annual_km": v["annual_km"],
                "load_factor": v["load_factor"],
                "fuel_type": fuel,
                "vkm": vkm,
                "co2_kg": round(co2_kg, 1),
                "equivalent_fuel_units": round(co2_kg / kg_per_unit[fuel], 1),
            })

        per_fuel = {}
        for fuel, disclosed in (("柴油", led["diesel_liters"]),
                                ("汽油", led["gasoline_liters"]),
                                ("LNG", led["lng_kg"])):
            if not disclosed:
                continue
            model_qty = sum(r["equivalent_fuel_units"] for r in rows
                            if r.get("fuel_type") == fuel and "equivalent_fuel_units" in r)
            same_fuel_rows = [r for r in rows if r.get("fuel_type") == fuel and "equivalent_fuel_units" in r]
            model_vkm = sum(r["vkm"] for r in same_fuel_rows)
            scale = disclosed / model_qty if model_qty else None
            # 披露燃料量按各车型等价比耗占比摊分，反推单车隐含百公里油耗，
            # 用于判断"车型构成 + 里程 + 披露能耗"三者是否彼此说得通。
            per_vehicle = []
            if model_qty:
                for r in same_fuel_rows:
                    share = r["equivalent_fuel_units"] / model_qty
                    alloc = disclosed * share
                    per_veh = alloc / r["count"] if r["count"] else 0.0
                    per_vehicle.append({
                        "vehicle_type": r["vehicle_type"],
                        "count": r["count"],
                        "annual_km": r["annual_km"],
                        "model_share": round(share, 4),
                        "allocated_disclosed_units": round(alloc, 1),
                        "implied_units_per_vehicle_year": round(per_veh, 1),
                        "implied_l_per_100km": round(per_veh / r["annual_km"] * 100, 2) if fuel != "LNG" else None,
                        "model_implied_l_per_100km": factors[r["vehicle_type"]]["fuel_consumption_l_per_100km"],
                    })
            per_fuel[fuel] = {
                "disclosed_qty": disclosed,
                "model_equivalent_qty": round(model_qty, 1),
                "ratio_model_over_disclosed": round(model_qty / disclosed, 4),
                "disclosed_qty_implied_total_vkm_km": round(model_vkm * scale, 0) if scale else None,
                "model_total_vkm_km": model_vkm,
                "implied_vehicle_fraction": round(scale, 4) if scale else None,
                "allocated_per_vehicle": per_vehicle,
            }

        out["cases"].append({
            "benchmark_id": b["benchmark_id"],
            "company_name": b["company_name"],
            "vehicles_total": sum(v["count"] for v in b["fleet_input"]),
            "rows": rows,
            "per_fuel": per_fuel,
        })

    return out


def report(result: dict) -> None:
    print("=" * 92)
    print(" 车队台账一致性核验：模型等效燃料量 vs 企业披露燃料量")
    print("=" * 92)
    print("说明：比值 = 按'车型构成 × 年均里程 × 排放因子'反算的等效燃料量 ÷ 披露燃料量。")
    print("      比值接近 1 表示活动参数与披露能耗在同一量级；偏离越大，说明二者越不自洽。")
    print("-" * 92)
    for c in result["cases"]:
        print(f"\n【{c['benchmark_id']}】{c['company_name']}（{c['vehicles_total']:,} 辆）")
        for fuel, m in c["per_fuel"].items():
            print(f"  · {fuel}：披露 {m['disclosed_qty']:,} | 模型等效 {m['model_equivalent_qty']:,}"
                  f" | 比值 {m['ratio_model_over_disclosed']:.4f}")
            print(f"      模型总车公里 {m['model_total_vkm_km']:,} km"
                  f" → 披露量可支撑 {m['disclosed_qty_implied_total_vkm_km']:,} km"
                  f"（相当于模型口径的 {m['implied_vehicle_fraction']:.1%}）")
            for pv in m.get("allocated_per_vehicle", []):
                tag = (f"{pv['implied_l_per_100km']:.1f} L/100km" if pv["implied_l_per_100km"] is not None
                       else f"{pv['implied_units_per_vehicle_year']:,.0f} kg/车/年")
                ref = (f"模型隐含 {pv['model_implied_l_per_100km']} L/100km"
                       if pv["model_implied_l_per_100km"] else "模型未给油耗")
                print(f"        - {pv['vehicle_type']}：摊分占比 {pv['model_share']:.1%}，"
                      f"单车 {pv['implied_units_per_vehicle_year']:,.0f} {fuel}单位/年"
                      f"（{tag}；{ref}）")
    print("\n" + "=" * 92)
    print("判读要点：")
    print("1. 比值在 0.93~1.12 之间（Case 2/3/4）时，可认为活动参数与披露能耗自洽；")
    print("2. 比值明显偏离 1 时（如 Case 1），说明该案例的车型构成/里程假设支撑不起披露能耗，")
    print("   或披露能耗只覆盖了车队的一部分，需回到原始报告核对分车型口径；")
    print("3. 本脚本只做核对，不修改任何输入数据，也不用于反向拟合参数。")
    print("=" * 92)


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    res = main()
    if "--json" in sys.argv:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        report(res)
        outp = PROJECT_ROOT / "docs" / "fleet_ledger_consistency.json"
        outp.write_text(json.dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"\n机器可读结果: {outp}")
