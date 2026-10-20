#!/usr/bin/env python3
"""端到端测试：模拟物流企业使用直接排放与减排情景流程。

场景：一家拥有100辆车的物流企业，计算直接运营排放和模拟碳预算情景。
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from src.engine.calculator import VehicleGroupData, calculate_emission
from src.engine.quota import estimate_quota_gap
from src.engine.carbon_price import estimate_compliance_cost, load_carbon_price_data
from src.engine.emission_factors import get_factor_comparison

def run_e2e_demo():
    print("=" * 60)
    print("🌿 物流碳排放与减排情景助手 — 端到端演示")
    print("=" * 60)
    
    # === 1. 企业车队数据 ===
    print("\n📋 企业：示例物流运输有限公司")
    fleet = [
        VehicleGroupData("重型柴油货车", 30, 80000, 0.75),
        VehicleGroupData("中型柴油货车", 40, 50000, 0.70),
        VehicleGroupData("轻型柴油货车", 20, 30000, 0.80),
        VehicleGroupData("新能源物流车", 10, 40000, 0.75),
    ]
    
    print(f"车队规模: {sum(g.count for g in fleet)} 辆")
    for g in fleet:
        print(f"  - {g.vehicle_type}: {g.count}辆, {g.annual_km:,}km/年, 满载率{g.load_factor:.0%}")
    
    # === 2. 碳排放基线计算 ===
    print("\n" + "=" * 60)
    print("📊 第一步：碳排放基线计算")
    print("=" * 60)
    
    baseline = calculate_emission(fleet)
    print(f"\n年度直接运营排放: {baseline.total_emission_t:,.1f} tCO2e")
    print(f"总车辆数: {baseline.total_vehicles} 辆")
    print("\n分车型排放明细:")
    print(f"{'车型':<16} {'排放量(tCO2e)':>14} {'占比':>8} {'单辆排放':>10}")
    for vtype, data in baseline.emission_by_type.items():
        print(f"  {vtype:<14} {data['排放量_tCO2']:>10.1f} {data['占比']:>7.1f}% {data['单辆排放_tCO2']:>8.1f}")
    
    # === 3. 模拟碳预算差额估算 ===
    print("\n" + "=" * 60)
    print("📋 第二步：模拟碳预算差额估算")
    print("=" * 60)
    
    fleet_summary = {}
    for v in fleet:
        fleet_summary[v.vehicle_type] = fleet_summary.get(v.vehicle_type, 0) + v.count
    gap = estimate_quota_gap(baseline.total_emission_t, fleet_summary)
    
    print(f"\n模拟碳预算:   {gap.total_quota_t:,.1f} tCO2e")
    print(f"直接运营排放: {gap.total_emission_t:,.1f} tCO2e")
    print(f"预算差额:     {gap.gap_t:,.1f} tCO2e")
    print(f"状态:         {gap.gap_status}")
    
    print("\n分车型模拟预算明细:")
    print(f"{'车型':<16} {'车辆数':>6} {'基准值':>8} {'预算(t)':>10}")
    for vtype, data in gap.quota_by_type.items():
        print(f"  {vtype:<14} {data['车辆数']:>4} {data['基准值_t_per_辆']:>6.0f} {data['模拟预算_t']:>8.1f}")
    
    # === 4. 碳价对标情景估算 ===
    print("\n" + "=" * 60)
    print("💰 第三步：碳价对标情景估算")
    print("=" * 60)
    
    price_df = load_carbon_price_data()
    cost = estimate_compliance_cost(gap.gap_t, price_df)
    
    print(f"\n情景判断: {cost['情景判断']}")
    if "预算差额_t" in cost:
        print(f"预算差额: {cost['预算差额_t']:,.1f} tCO2e")
        print(f"当前碳价: {cost['当前碳价_元每吨']} 元/吨")
        print(f"近90日均价: {cost.get('近90日均价_元每吨', 'N/A')} 元/吨")
        print(f"碳价离散度CV: {cost.get('碳价离散度CV', 'N/A')}")
        print(f"\n情景成本: {cost['情景成本_参考价']:,.0f} 元")
        print(f"成本区间: {cost['情景成本区间_low']:,.0f} ~ {cost['情景成本区间_high']:,.0f} 元")
    elif "预算结余_t" in cost:
        print(f"预算结余: {cost['预算结余_t']:,.1f} tCO2e")
        print(f"潜在价值: {cost['潜在价值_low']:,.0f} ~ {cost['潜在价值_high']:,.0f} 元")
    print(f"口径说明: {cost['备注']}")
    
    # === 5. 排放因子对比 ===
    print("\n" + "=" * 60)
    print("📈 排放因子数据来源对比")
    print("=" * 60)
    
    comparison = get_factor_comparison()
    print(f"\n{'车型':<20} {'环境科学2021':>12} {'GB2024':>8} {'GB2018':>8} {'推荐值':>8}")
    for c in comparison:
        gb24 = f"{c.get('gb_2024'):>8.3f}" if c.get('gb_2024') else "     N/A"
        gb18 = f"{c.get('gb_2018'):>8.3f}" if c.get('gb_2018') else "     N/A"
        print(f"  {c['vehicle_type']:<18} {c['env_science_2021']:>10.3f} {gb24} {gb18} {c['recommended']:>6.3f}")
    
    # === 6. 总结 ===
    print("\n" + "=" * 60)
    print("📝 企业排放与减排情景总结")
    print("=" * 60)
    print(f"""
企业: 示例物流运输有限公司
车队: {baseline.total_vehicles} 辆（含{fleet[3].count}辆新能源车）
直接运营排放: {baseline.total_emission_t:,.1f} tCO2e
模拟碳预算:   {gap.total_quota_t:,.1f} tCO2e
预算差额:     {gap.gap_t:,.1f} tCO2e（{gap.gap_status}）
情景金额:     {cost.get('情景成本_参考价', cost.get('潜在价值_low', 0)):,.0f} 元

建议:
1. {'直接运营排放高于模拟预算，应优先评估减排措施' if gap.gap_t > 0 else '直接运营排放低于模拟预算，但差额不等同于可出售配额'}
2. 新能源车替代可减少直接运营排放约{fleet[3].count * 40000 * 0.877 / 1000:.0f} tCO2e/年（未计购电间接排放）
3. 提高满载率可降低单位排放（满载率从70%→75%约减少2%排放）
4. 碳价仅用于情景对标，不代表物流企业当前履约成本
""")
    
    print("✅ 端到端测试完成")

if __name__ == "__main__":
    run_e2e_demo()
