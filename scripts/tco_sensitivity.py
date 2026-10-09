#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""TCO 关键假设敏感性：充换电单价 × 年里程 对静态回收期的影响。

为什么需要这个脚本
------------------
主分析里的回收期是在单一假设下算出来的：综合电价 0.80 元/kWh、年里程固定
（轻卡 3.5 万 km、重卡 10 万 km）。但实际项目里这两个数都会变：
换电站的服务费通常高于普通充电，且车队的年里程差异很大。
只报一组数字，无法回答"什么条件下这个结论会失效"。

做法
----
直接调用 `src/engine/tco.py` 的 `calculate_single_vehicle_tco()`，
对"充换电单价 × 年里程"做二维扫描，记录：
- 静态回收期（年）；
- 当 ΔOPEX ≤ 0（运营节约被电池租金/电价吃掉）时，标记为"不可回收"。

不做任何参数拟合，只做确定性重算。

用法（仓库根目录）：
    python scripts/tco_sensitivity.py                 # 打印两张网格表
    python scripts/tco_sensitivity.py --json
    python scripts/tco_sensitivity.py --out docs/tco_sensitivity_report.md
"""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from src.engine.calculator import calculate_load_adjustment  # noqa: E402
from src.engine.reduction import REPLACEMENT_MAP  # noqa: E402
from src.engine.tco import (  # noqa: E402
    TCOEconomicParameters,
    calculate_single_vehicle_tco,
)

VEHICLES = {
    "轻型柴油货车": {
        "label": "城配轻卡",
        "benchmark_km": 35000,
        "km_grid": [20000, 30000, 35000, 45000, 60000],
        "load_factor": 0.65,
        "price_grid": [0.60, 0.80, 1.00, 1.20, 1.50],
        "baas_discount_wan": 5.0,
        "baas_rental_yuan": 13500.0,
    },
    "重型柴油货车": {
        "label": "干线重卡",
        "benchmark_km": 100000,
        "km_grid": [60000, 80000, 100000, 120000, 140000],
        "load_factor": 0.70,
        "price_grid": [0.60, 0.80, 1.00, 1.20, 1.50],
        "baas_discount_wan": 20.0,
        "baas_rental_yuan": 45000.0,
    },
}


def annual_reduction(vt: str, count: int, km: float, lf: float) -> float:
    """与 src/engine/reduction.py 同口径的年直接减排量 (tCO2e)。"""
    ef_old = REPLACEMENT_MAP.get(vt, (None, 0.877))[1]
    return count * km * ef_old * calculate_load_adjustment(lf) / 1000.0


def run_grid(vt: str, cfg: dict, mode: str) -> list:
    rows = []
    for price in cfg["price_grid"]:
        row = []
        for km in cfg["km_grid"]:
            params = TCOEconomicParameters(
                lifespan_years=5,
                electricity_price_yuan_per_kwh=price,
                is_baas_mode=(mode == "baas"),
                baas_chassis_discount_wan=cfg["baas_discount_wan"] if mode == "baas" else 0.0,
                baas_annual_battery_rental_yuan=cfg["baas_rental_yuan"] if mode == "baas" else 0.0,
            )
            r = calculate_single_vehicle_tco(
                vt, 20, float(km), annual_reduction(vt, 20, float(km), cfg["load_factor"]),
                econ_params=params)
            opex = r.annual_opex_saving_total_yuan / 20.0
            row.append({
                "price_yuan_per_kwh": price,
                "annual_km": km,
                "delta_capex_per_vehicle_wan": round(r.delta_capex_per_vehicle_yuan / 10000.0, 3),
                "delta_opex_per_vehicle_wan": round(opex / 10000.0, 3),
                "payback_years": (round(r.payback_period_years, 2)
                                  if r.payback_period_years else None),
                "feasible": bool(opex > 0),
            })
        rows.append(row)
    return rows


def fmt(rows: list, key: str = "payback_years") -> str:
    km_grid = [c["annual_km"] for c in rows[0]]
    price_grid = [r[0]["price_yuan_per_kwh"] for r in rows]
    head = "| 电价(元/kWh) \\ 年里程(km) | " + " | ".join(f"{k:,}" for k in km_grid) + " |"
    sep = "| :---: | " + " | ".join(":---:" for _ in km_grid) + " |"
    lines = [head, sep]
    for price, row in zip(price_grid, rows):
        cells = []
        for c in row:
            if not c["feasible"]:
                cells.append("不可回收")
            elif key == "payback_years":
                cells.append(f"{c['payback_years']:.2f}")
            else:
                cells.append(f"{c[key]:.2f}")
        lines.append(f"| **{price:.2f}** | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def main() -> dict:
    out = {}
    for vt, cfg in VEHICLES.items():
        out[vt] = {
            "label": cfg["label"],
            "benchmark_km": cfg["benchmark_km"],
            "km_grid": cfg["km_grid"],
            "price_grid": cfg["price_grid"],
            "purchase": run_grid(vt, cfg, "purchase"),
            "baas": run_grid(vt, cfg, "baas"),
        }
    return out


def write_report(res: dict, path: Path) -> None:
    lines = [
        "# TCO 关键假设敏感性报告（充换电单价 × 年里程）",
        "",
        "> 由 `scripts/tco_sensitivity.py` 生成，调用 `src/engine/tco.py` 的确定性重算，",
        "> 不含任何拟合。基准假设：评估期 5 年，柴油 7.50 元/L，维保节省 35%。",
        "> 表中数值为**单车静态回收期（年）**；标注\"不可回收\"表示在该组合下",
        "> 年运营节约 ≤ 0（电价与电池租金吃掉了全部节省），回收期不存在。",
        "",
    ]
    for vt, d in res.items():
        lines += [f"## {d['label']}（{vt}）", "",
                  f"基准年里程 {d['benchmark_km']:,} km/年。", "",
                  "### 整车买断模式", "", fmt(d["purchase"]), "",
                  "### BaaS 车电分离模式", "", fmt(d["baas"]), ""]
    lines += [
        "## 读法",
        "",
        "1. 横向比较：在同一电价下，年里程越高回收越快，因为节能收益与里程成正比，",
        "   而购置增量和电池租金基本固定；",
        "2. 纵向比较：电价越高回收越慢。当充换电单价升到一定程度，BaaS 模式会出现",
        "   \"不可回收\"区域——这正是主分析只给单点数值时无法暴露的风险；",
        "3. 本表未计入电池衰减与更换、车辆残值、充换电排队时间、重卡大功率充电桩真实造价；",
        "   这些项都会使回收期变长，因此表内数值应视为乐观一侧的估计。",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="TCO 充换电单价 × 年里程敏感性")
    ap.add_argument("--json", action="store_true", help="输出 JSON")
    ap.add_argument("--out", default=None, help="Markdown 报告输出路径")
    args = ap.parse_args()

    res = main()
    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        for vt, d in res.items():
            print("=" * 84)
            print(f" {d['label']}（{vt}）单车静态回收期（年），基准里程 {d['benchmark_km']:,} km/年")
            print("=" * 84)
            print("\n[整车买断]\n" + fmt(d["purchase"]))
            print("\n[BaaS 车电分离]\n" + fmt(d["baas"]))
            print()
    if args.out:
        p = Path(args.out)
        p.parent.mkdir(parents=True, exist_ok=True)
        write_report(res, p)
        print(f"报告已写入: {p}")
    else:
        write_report(res, PROJECT_ROOT / "docs" / "tco_sensitivity_report.md")
        print(f"报告已写入: {PROJECT_ROOT / 'docs' / 'tco_sensitivity_report.md'}")
