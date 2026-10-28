#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""小样本无台账车队的误差包络（GAP-4 回应）

问题
----
`docs/known_gaps.md` GAP-4 自陈：4 个实证案例都是披露了燃料台账的**头部企业**
（合计 51,990 辆），而项目诉求是服务**无台账的中小车队**——验证集与目标用户
不是同一群体。因此「等权 MAPE 4.23%」不能外推给一个只有 20 辆车、说不出准确
年里程的老板。

本脚本做什么，不做什么
----------------------
**做**：在「无台账」条件下，把输入不确定性传播成输出误差包络。
给定车队只有车型与大致辆数（里程与满载率只能按行业参考值猜），
枚举里程与满载率的合理猜测误差，统计估算排放量相对「真值」的相对偏差分布。

**不做**：不声称这是准确率验证。这里没有真实台账可比——真值本身由引擎按
一组「真实但不可观测」的参数算出，误差来源只有输入猜测偏差。
它回答的是「输入错到这种程度，输出会错多少」，不是「模型对不对」。

与 `scripts/sensitivity_analysis.py` 的区别
------------------------------------------
前者在**有台账**的 4 家车队上做扰动，误差 = 模型 vs 燃料台账；
本脚本在**无台账**的合成车队上做扰动，误差 = 估算 vs 同引擎真值。
两者的数字不可互相替代，报告里必须分开写。

用法（仓库根目录）：
    python scripts/small_fleet_envelope.py
    python scripts/small_fleet_envelope.py --out data/processed/small_fleet_envelope.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

from src.engine.calculator import VehicleGroupData, calculate_emission  # noqa: E402

DEFAULT_OUT = PROJECT_ROOT / "data" / "processed" / "small_fleet_envelope.json"

#: 目标用户画像：中小车队，10–50 辆，车型混合，无燃料台账。
#: 里程与满载率只能按行业参考值猜——这是"无台账"的真实含义。
SMALL_FLEET_PROFILES = [
    {
        "name": "城配冷链（20 辆）",
        "mix": [("轻型柴油货车", 12), ("中型柴油货车", 6), ("新能源物流车", 2)],
        "true_km": {"轻型柴油货车": 42000, "中型柴油货车": 58000, "新能源物流车": 31000},
        "true_load": {"轻型柴油货车": 0.62, "中型柴油货车": 0.71, "新能源物流车": 0.66},
    },
    {
        "name": "区域干线（35 辆）",
        "mix": [("重型柴油货车", 20), ("中型柴油货车", 15)],
        "true_km": {"重型柴油货车": 96000, "中型柴油货车": 64000},
        "true_load": {"重型柴油货车": 0.78, "中型柴油货车": 0.74},
    },
    {
        "name": "市内配送（12 辆）",
        "mix": [("微型汽油货车", 7), ("轻型柴油货车", 5)],
        "true_km": {"微型汽油货车": 26000, "轻型柴油货车": 34000},
        "true_load": {"微型汽油货车": 0.58, "轻型柴油货车": 0.64},
    },
    {
        "name": "混编车队（50 辆）",
        "mix": [("重型柴油货车", 12), ("中型柴油货车", 16),
                ("轻型柴油货车", 14), ("新能源物流车", 8)],
        "true_km": {"重型柴油货车": 88000, "中型柴油货车": 61000,
                    "轻型柴油货车": 38000, "新能源物流车": 30000},
        "true_load": {"重型柴油货车": 0.75, "中型柴油货车": 0.70,
                      "轻型柴油货车": 0.63, "新能源物流车": 0.68},
    },
]

#: 里程猜测误差（相对真值）与满载率猜测误差（绝对偏移）。
#: 依据：中小车队通常能说出"大概跑多少万公里"，但拿不出年度读数，±25% 已是
#: 乐观估计；满载率在没有调度系统时基本靠印象，偏 0.20 是常见量级。
#
#: 注意这两组是**假设的上界**，不是观测到的分布。因此下文只报"包络"与
#: "误差预算"，不报中位数、不报命中率——在对称枚举网格上算分位数，
#: 得到的只是网格构造的产物（中位数恒为 0、各画像数值几乎相同），
#: 看起来像发现，其实什么也没测。
KM_ERRORS = [-0.25, -0.15, -0.05, 0.0, 0.05, 0.15, 0.25]
LOAD_ERRORS = [-0.20, -0.10, 0.0, 0.10, 0.20]

#: 满载率猜测误差的结构性上界（解析可得，不依赖网格）。
#: LF(l) = 1 + 0.15·max(0, 0.75-l)，值域 [1, 1.1125]。
#: 因此无论把满载率猜得多离谱，它单独造成的偏差都不会超过
#: 上界 +11.25%（真值 LF=1.0、猜 0）与下界 −10.1%（真值 LF=1.1125、猜 1.0）。
LF_DESIGN_CAP = 0.15 * 0.75          # = 0.1125
LF_UPPER_BOUND_PCT = LF_DESIGN_CAP * 100
LF_LOWER_BOUND_PCT = (1.0 / (1 + LF_DESIGN_CAP) - 1) * 100


def _emission(mix, km_by_type, load_by_type) -> float:
    groups = [
        VehicleGroupData(
            vehicle_type=vtype,
            count=count,
            annual_km=km_by_type[vtype],
            load_factor=load_by_type[vtype],
        )
        for vtype, count in mix
    ]
    return calculate_emission(groups).total_emission_t


def _scaled(profile, km_err: float, load_err: float) -> float:
    km_guess = {v: km * (1 + km_err) for v, km in profile["true_km"].items()}
    load_guess = {
        v: min(1.0, max(0.0, lf + load_err)) for v, lf in profile["true_load"].items()
    }
    return _emission(profile["mix"], km_guess, load_guess)


def analyse_profile(profile) -> dict:
    """给出该画像的误差包络、因素分解与误差预算。

    只报三类可解释的量，不报分位数：
    - envelope：「里程与满载率同时猜错到假设上界」时的最大/最小偏差；
    - decomposition：单因素分别能造成多大偏差，用来回答「先补哪个数据」；
    - km_budget：要保证总误差落在 ±10% 内，里程需要猜准到什么程度。
    """
    true_value = _emission(profile["mix"], profile["true_km"], profile["true_load"])

    def pct(est: float) -> float:
        return (est - true_value) / true_value * 100

    # 包络：遍历假设网格取极值（这是界，不是分布）
    grid = [
        pct(_scaled(profile, km_err, load_err))
        for km_err in KM_ERRORS
        for load_err in LOAD_ERRORS
    ]

    # 单因素：另一个因素固定为真值
    km_only = max(abs(pct(_scaled(profile, e, 0.0))) for e in KM_ERRORS)
    load_only = max(abs(pct(_scaled(profile, 0.0, e))) for e in LOAD_ERRORS)

    # 误差预算：里程偏差放宽到多少时，仍能保证（在最坏满载率猜测下）|总误差|<=10%
    budget = 0.0
    for step in range(0, 26):
        km_err = step / 100.0
        worst = max(abs(pct(_scaled(profile, km_err, le))) for le in LOAD_ERRORS)
        if worst <= 10.0:
            budget = km_err
        else:
            break

    worst_case = max(
        (
            {"km_error_pct": round(km_err * 100, 1), "load_error": round(load_err, 2),
             "estimate_t": round(_scaled(profile, km_err, load_err), 2),
             "rel_err_pct": round(pct(_scaled(profile, km_err, load_err)), 2)}
            for km_err in KM_ERRORS for load_err in LOAD_ERRORS
        ),
        key=lambda d: abs(d["rel_err_pct"]),
    )

    total_vehicles = sum(c for _, c in profile["mix"])
    return {
        "profile": profile["name"],
        "vehicles": total_vehicles,
        "true_emission_t": round(true_value, 2),
        "envelope_pct": {"min": round(min(grid), 2), "max": round(max(grid), 2)},
        "decomposition_pct": {
            "km_only_max_abs": round(km_only, 2),
            "load_only_max_abs": round(load_only, 2),
        },
        "km_budget_for_10pct": round(budget, 2),
        "worst_case": worst_case,
    }


def analyse_all() -> dict:
    rows = [analyse_profile(p) for p in SMALL_FLEET_PROFILES]
    return {
        "note": (
            "本文件是无台账小样本车队的**输入不确定性传播包络**，不是准确率验证。"
            "真值由同一引擎按一组不可观测的『真实』参数算出，误差只来自输入猜测偏差；"
            "与 scripts/sensitivity_analysis.py（有台账车队、模型 vs 燃料台账）不可互换引用。"
        ),
        "design": {
            "profiles": len(SMALL_FLEET_PROFILES),
            "km_error_grid": [f"{e:+.0%}" for e in KM_ERRORS],
            "load_error_grid": [f"{e:+.2f}" for e in LOAD_ERRORS],
            "n_variants_per_profile": len(KM_ERRORS) * len(LOAD_ERRORS),
            "generated_by": "scripts/small_fleet_envelope.py",
        },
        "profiles": rows,
    }


def write_report(payload: dict, path: Path) -> None:
    rows = payload["profiles"]
    worst_abs = max(abs(r["worst_case"]["rel_err_pct"]) for r in rows)
    km_dominant = all(
        r["decomposition_pct"]["km_only_max_abs"] > r["decomposition_pct"]["load_only_max_abs"]
        for r in rows
    )

    lines = [
        "# 小样本无台账车队的误差包络",
        "",
        "> 本文件由 `scripts/small_fleet_envelope.py --out` 自动生成，数字均为现算，不手工维护。",
        "",
        "## 一、这份分析回答什么",
        "",
        "`docs/known_gaps.md` GAP-4 承认：4 个实证案例都是有燃料台账的头部企业，",
        "而目标用户是无台账的中小车队。所以「等权 MAPE 4.23%」不能直接外推给一个",
        "只有 20 辆车、说不出准确年里程的老板。本节回答的是：",
        "",
        "**在无台账条件下，输入猜错到假设上界，估算结果会偏多少？先补哪个数据最有效？**",
        "",
        "> ⚠️ 这不是准确率验证。真值是同一引擎按一组不可观测的「真实」参数算出的，",
        "> 误差只来自输入猜测偏差，不含模型结构误差。它不能与 4.23% 那个",
        "> 「模型 vs 燃料台账」的读数互相替代，报告与答辩材料中必须分开引用。",
        ">",
        "> ⚠️ 也不报中位数或命中率：里程与满载率是**假设的上界**而非观测分布，",
        "> 在对称枚举网格上算分位数只会得到网格构造的产物（中位数恒为 0、",
        "> 各画像数值几乎相同），看着像发现，实际什么也没测。",
        "",
        "## 二、场景设置",
        "",
        f"- 车队画像：{payload['design']['profiles']} 个（10–50 辆，车型混合，无燃料台账）",
        f"- 里程猜测误差假设：{'、'.join(payload['design']['km_error_grid'])}",
        f"- 满载率猜测误差假设：{'、'.join(payload['design']['load_error_grid'])}",
        f"- 每个画像枚举组合数：{payload['design']['n_variants_per_profile']}",
        "",
        "## 三、误差包络与因素分解",
        "",
        "| 车队画像 | 车辆数 | 真实排放 (t) | 偏差包络 | 单因素：仅里程 | 单因素：仅满载率 | 里程需猜准到 |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        env = r["envelope_pct"]
        dec = r["decomposition_pct"]
        budget = r["km_budget_for_10pct"]
        budget_text = f"±{budget:.0%}" if budget > 0 else "任何里程误差都无法保证"
        lines.append(
            f"| {r['profile']} | {r['vehicles']} | {r['true_emission_t']:,.0f} | "
            f"{env['min']:+.0f}% ~ {env['max']:+.0f}% | "
            f"{dec['km_only_max_abs']:.0f}% | {dec['load_only_max_abs']:.0f}% | {budget_text} |"
        )

    lines += [
        "",
        f"- 全部画像、全部组合中的最大偏差：**{worst_abs:.1f}%**",
        f"- 「仅里程」是否在所有画像上都大于「仅满载率」的效应：**{'是' if km_dominant else '否'}**",
        f"- 满载率单独造成的偏差有解析上界：最多 **+{LF_UPPER_BOUND_PCT:.2f}%**，"
        f"最少 **{LF_LOWER_BOUND_PCT:.1f}%**。原因是 LF 值域被设计为 [1, "
        f"{1 + LF_DESIGN_CAP:.4f}]，无论把满载率猜得多离谱都越不出这个范围。",
        "",
        "## 四、结论与适用边界",
        "",
        "1. **无台账时误差量级远大于有台账**：有台账的 4 家车队标定误差为 4.23%，",
        f"   而同一引擎在无台账输入下最大偏差达 {worst_abs:.0f}%。差别不在模型结构，",
        "   在活动数据质量——这正是 GAP-4 的实际后果，应当明说而不是回避。",
        "2. **里程是主导因素，且它的影响是线性的**：里程猜高 25%，排放量就高 25%；",
        "   满载率则受 LF 设计上界约束，单独最多只会带来约 ±11% 的偏差。",
        "   因此部署建议是：优先帮用户拿到 1–2 个代表车型的实测里程",
        "   （年检记录、车载终端），满载率可以用区间输入加保守偏置。",
        "3. **「里程需猜准到」一列是本节的实用产出**：它给出「要把总误差控制在 ±10%",
        "   以内，里程至少得准到什么程度」。该列由脚本逐档试算得出，不是估计值。",
        "4. **只用于「区间披露」**：合理表述是「20 辆城配车队年排放约 X 吨，",
        "   在输入偏差假设下落在 [A, B]」，不应给出单一数字并称其为准确值。",
        "   反过来说，凡是要给点估计的场合，都必须先取得实测里程。",
        "",
        "## 五、复现",
        "",
        "```bash",
        "python scripts/small_fleet_envelope.py --out data/processed/small_fleet_envelope.json",
        "```",
        "",
        "守卫测试：`tests/test_small_fleet_envelope.py`",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=DEFAULT_OUT, help="结果 JSON 输出路径")
    args = ap.parse_args()

    payload = analyse_all()

    # 每条画像的真实排放都要能算出来，否则说明车型名与因子表不匹配
    for r in payload["profiles"]:
        assert r["true_emission_t"] > 0, f"{r['profile']} 真实排放为 0"

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    report = PROJECT_ROOT / "docs" / "small_fleet_envelope.md"
    write_report(payload, report)

    print(f"{'车队画像':<20}{'车辆数':>6}{'真实排放(t)':>14}{'偏差包络':>16}"
          f"{'仅里程':>9}{'仅满载率':>10}{'里程预算':>10}")
    print("-" * 88)
    for r in payload["profiles"]:
        env = r["envelope_pct"]
        dec = r["decomposition_pct"]
        budget = r["km_budget_for_10pct"]
        budget_text = f"±{budget:.0%}" if budget > 0 else "无法保证"
        print(
            f"{r['profile']:<18}{r['vehicles']:>6}{r['true_emission_t']:>14,.0f}"
            f"{env['min']:>8.0f}~{env['max']:>6.0f}%{dec['km_only_max_abs']:>8.0f}%"
            f"{dec['load_only_max_abs']:>9.0f}%{budget_text:>10}"
        )
    print(f"\n✅ 结果: {args.out.relative_to(PROJECT_ROOT)}")
    print(f"✅ 报告: {report.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
