"""复现脚本：核实 reduction.py 多车型/多措施场景下的重复统计 Bug

用法: python3 scripts/repro_reduction_bug.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from src.engine.calculator import VehicleGroupData, calculate_emission
from src.engine.reduction import (
    _build_scenario_fleet,
    _summarize_fleet,
    ReductionScenario,
    compare_scenarios,
)


def section(title):
    print(f"\n{'='*60}\n{title}\n{'='*60}")


def check(name, cond, detail=""):
    status = "PASS" if cond else "FAIL"
    print(f"  [{status}] {name}" + (f"  ({detail})" if detail else ""))
    return cond


results = []

# ---------------------------------------------------------------
section("场景1：多车型 + 单一新能源替换措施（车辆数守恒）")
fleet = [
    VehicleGroupData(vehicle_type="重型柴油货车", count=50, annual_km=80000, load_factor=0.70),
    VehicleGroupData(vehicle_type="中型柴油货车", count=30, annual_km=50000, load_factor=0.75),
]
scen = _build_scenario_fleet(fleet, {"替换为新能源物流车": 15})
total = sum(g.count for g in scen)
print(f"  基线 80 辆 -> 情景 {total} 辆; 分组: {[(g.vehicle_type, g.count) for g in scen]}")
results.append(check("车辆数守恒 (80=80)", total == 80, f"实际 {total}"))

# ---------------------------------------------------------------
section("场景2：多车型 + 新能源替换数量超过单一车型（跨车型顺序消费）")
# 语义问题候选：若用户意图是"每种车型各替换10辆"，代码实际只替换重型10辆+...顺序消费
scen = _build_scenario_fleet(fleet, {"替换为新能源物流车": 10})
ev = sum(g.count for g in scen if g.vehicle_type == "新能源物流车")
print(f"  替换10辆 -> 新能源车总数 {ev}; 分组: {[(g.vehicle_type, g.count) for g in scen]}")
results.append(check("新能源替换 10 辆只出现一次", ev == 10, f"实际 {ev}"))

# ---------------------------------------------------------------
section("场景3：多车型 + 多措施组合（新能源+LNG+满载率）——重复统计高发区")
fleet3 = [
    VehicleGroupData(vehicle_type="重型柴油货车", count=50, annual_km=80000, load_factor=0.70),
    VehicleGroupData(vehicle_type="中型柴油货车", count=30, annual_km=50000, load_factor=0.75),
    VehicleGroupData(vehicle_type="轻型柴油货车", count=20, annual_km=30000, load_factor=0.60),
]
changes3 = {
    "替换为新能源物流车": 20,   # 期望：总20辆燃油车变新能源
    "重型货车更换LNG": 10,     # 期望：总10辆柴油车变LNG
    "提升满载率至0.8": 40,     # 期望：总40辆未达0.8的车提升
}
scen3 = _build_scenario_fleet(fleet3, changes3)
summary3 = {}
for g in scen3:
    summary3[g.vehicle_type] = summary3.get(g.vehicle_type, 0) + g.count
total3 = sum(g.count for g in scen3)
print(f"  基线 {sum(g.count for g in fleet3)} 辆 -> 情景 {total3} 辆")
print(f"  分组统计: {summary3}")
print(f"  分组明细: {[(g.vehicle_type, g.count, g.load_factor) for g in scen3]}")
results.append(check("车辆数守恒 (100=100)", total3 == sum(g.count for g in fleet3), f"实际 {total3}"))
results.append(check("新能源车总数 = 20", summary3.get("新能源物流车", 0) == 20, f"实际 {summary3.get('新能源物流车', 0)}"))
results.append(check("LNG车总数 = 10", summary3.get("LNG重型货车", 0) == 10, f"实际 {summary3.get('LNG重型货车', 0)}"))
# 满载率提升的车辆数无法直接从分组看出，用排放反推：
base_emission3 = calculate_emission(fleet3).total_emission_t
scen_emission3 = calculate_emission(scen3).total_emission_t
print(f"  基线排放 {base_emission3:.2f} t -> 情景排放 {scen_emission3:.2f} t")

# ---------------------------------------------------------------
section("场景4：同车型多组输入（用户分两行输入同一车型）→ quota summary 口径")
fleet4 = [
    VehicleGroupData(vehicle_type="重型柴油货车", count=30, annual_km=80000, load_factor=0.70),
    VehicleGroupData(vehicle_type="重型柴油货车", count=20, annual_km=80000, load_factor=0.75),
]
e4 = calculate_emission(fleet4).total_emission_t
# 修复后：_summarize_fleet 按车型累加，不丢组
summary4 = _summarize_fleet(fleet4)
print(f"  排放(加总) {e4:.2f} t; 修复后summary 重型车数 {summary4.get('重型柴油货车')} (应为50)")
results.append(check("修复后同车型多组合并", summary4.get("重型柴油货车") == 50, f"实际 {summary4.get('重型柴油货车')}"))
# 对照旧写法（bug 复现）：
legacy4 = {g.vehicle_type: g.count for g in fleet4}
print(f"  [对照] 旧 dict 覆盖写法重型车数 {legacy4.get('重型柴油货车')}（历史 bug，仅存档演示）")

# ---------------------------------------------------------------
section("场景5：compare_scenarios 对同车型多组输入的排序正确性")
r4 = compare_scenarios(fleet4, [
    ReductionScenario(name="换5辆", description="", changes={"替换为新能源物流车": 5}),
])
print(f"  情景数 {len(r4.scenarios)}; 最优 {r4.scenarios[0].name if r4.scenarios else 'N/A'}")

print(f"\n{'='*60}\n汇总: {sum(results)}/{len(results)} 通过\n{'='*60}")
sys.exit(0 if all(results) else 1)
