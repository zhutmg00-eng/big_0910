"""TCO (Total Cost of Ownership) 全生命周期综合拥有成本与投资决策引擎。

核心数学模型：
1. CAPEX 差异（初始购置与充电增量）：
   ΔCAPEX = (单车购车价_EV - 单车购车价_ICE + 充电桩分摊) × 替换车辆数
2. OPEX 年度运营节省（能耗 + 维保）：
   - 燃油车年能耗：C_fuel = (年里程 / 100) × 百公里油耗(L) × 柴油/汽油单价(元/L)
   - 新能源年电耗：C_elec = (年里程 / 100) × 百公里电耗(kWh) × 综合电价(元/kWh)
   - 维保节省：燃油车年维保基准 × 维保节省率
   - 年度总节省：ΔOPEX = (C_fuel - C_elec + 维保节省) × 替换车辆数
3. 静态投资回收期（年）：
   T_payback = ΔCAPEX / ΔOPEX
4. 单位吨碳减排边际成本（MAC, 元/tCO2e）：
   MAC = (ΔCAPEX - Σ[ΔOPEX_t / (1+r)^t]) / 全周期总减碳量
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class VehicleTCOBenchmark:
    """车型 TCO 基础经济与能耗基准参数。"""

    ice_vehicle_price_wan: float  # 燃油车购车单价（万元）
    ev_vehicle_price_wan: float  # 新能源纯电车购车单价（万元）
    charger_cost_wan: float  # 充电桩配套分摊（万元/车）
    fuel_consumption_per_100km: float  # 燃油车百公里油耗（L/100km）
    electricity_consumption_per_100km: float  # 纯电车百公里电耗（kWh/100km）
    fuel_type: str  # 燃料类型：柴油 / 汽油
    annual_maintenance_ice_yuan: float  # 燃油车年维保基准（元/年/车）
    maintenance_saving_ratio: float = 0.35  # 新能源维保节省比例（默认35%）


# 行业主流商用货车 TCO 默认基准库
DEFAULT_TCO_BENCHMARKS: Dict[str, VehicleTCOBenchmark] = {
    "重型柴油货车": VehicleTCOBenchmark(
        ice_vehicle_price_wan=35.0,
        ev_vehicle_price_wan=65.0,
        charger_cost_wan=3.0,
        fuel_consumption_per_100km=33.0,
        electricity_consumption_per_100km=140.0,
        fuel_type="柴油",
        annual_maintenance_ice_yuan=15000.0,
        maintenance_saving_ratio=0.35,
    ),
    "中型柴油货车": VehicleTCOBenchmark(
        ice_vehicle_price_wan=18.0,
        ev_vehicle_price_wan=30.0,
        charger_cost_wan=1.5,
        fuel_consumption_per_100km=19.0,
        electricity_consumption_per_100km=75.0,
        fuel_type="柴油",
        annual_maintenance_ice_yuan=9000.0,
        maintenance_saving_ratio=0.35,
    ),
    "轻型柴油货车": VehicleTCOBenchmark(
        ice_vehicle_price_wan=11.0,
        ev_vehicle_price_wan=17.0,
        charger_cost_wan=0.8,
        fuel_consumption_per_100km=12.0,
        electricity_consumption_per_100km=35.0,
        fuel_type="柴油",
        annual_maintenance_ice_yuan=6000.0,
        maintenance_saving_ratio=0.35,
    ),
    "微型汽油货车": VehicleTCOBenchmark(
        ice_vehicle_price_wan=5.0,
        ev_vehicle_price_wan=8.0,
        charger_cost_wan=0.3,
        fuel_consumption_per_100km=8.0,
        electricity_consumption_per_100km=20.0,
        fuel_type="汽油",
        annual_maintenance_ice_yuan=3500.0,
        maintenance_saving_ratio=0.30,
    ),
}


@dataclass
class TCOEconomicParameters:
    """宏观经济与通用能源价格参数。"""

    diesel_price_yuan_per_l: float = 7.50  # 柴油单价（元/L）
    gasoline_price_yuan_per_l: float = 7.80  # 汽油单价（元/L）
    electricity_price_yuan_per_kwh: float = 0.80  # 综合电价（元/kWh）
    discount_rate: float = 0.06  # 年贴现率 r（默认6%）
    lifespan_years: int = 5  # 车辆运营评估周期 N（年）
    is_baas_mode: bool = False  # 是否启用换电车电分离 (BaaS, Battery as a Service) 模式
    baas_chassis_discount_wan: float = 0.0  # 剥离动力电池后的单车购置立减金额（万元/车，默认重卡20万，其他按比例）
    # 单车年电池租赁费（元/年/车）。填 0 表示"未指定"，此时按车型回落内置档位：
    # 重卡 45,000 / 中型 22,000 / 轻型 12,000 / 其它 5,000（见 calculate_single_vehicle_tco）。
    # 显式填正数则完全覆盖内置档位——论文表 6 的轻卡 0.97 年即取 13,500，高于轻型默认档 12.5%。
    baas_annual_battery_rental_yuan: float = 0.0


@dataclass
class SingleVehicleTCOResult:
    """单车及同车型批量替换的 TCO 分析结果。"""

    target_vehicle_type: str  # 目标燃油车型
    replace_count: int  # 替换车辆数
    annual_km: float  # 单车年均里程 (km)
    delta_capex_total_yuan: float  # 初始总投资增量（元）
    delta_capex_per_vehicle_yuan: float  # 单车投资增量（元/辆）
    annual_fuel_cost_per_vehicle_yuan: float  # 燃油车年能耗费（元/车）
    annual_elec_cost_per_vehicle_yuan: float  # 纯电车年电费（元/车）
    annual_energy_saving_total_yuan: float  # 全车队年能耗节省总额（元/年）
    annual_maintenance_saving_total_yuan: float  # 全车队年维保节省总额（元/年）
    annual_opex_saving_total_yuan: float  # 全车队年运营节省总额 ΔOPEX（元/年）
    payback_period_years: Optional[float]  # 静态投资回收期（年）
    mac_yuan_per_tco2e: Optional[float]  # 单位吨碳减排边际成本 MAC (元/tCO2e)
    annual_co2_reduction_t: float  # 年直接减排量 (tCO2e)
    lifespan_co2_reduction_t: float  # 全生命周期总减排量 (tCO2e)
    lifespan_net_savings_yuan: float  # 全生命周期净节省 (NPV折现后净现值收益，元)
    yearly_cumulative_cashflow_yuan: List[float] = field(default_factory=list)  # 0~N年累计现金流
    # BaaS 宣称的"初始垫资骤降 xx%"来自哪里，必须显式写出来。
    # 详见 baas_capex_note：这个比例是代数恒等式的算术结果，不是敏感性分析的结论，
    # 拿它当卖点时评委一问"充电桩单价取多少"就答不上来。
    baas_capex_note: str = ""


@dataclass
class FleetTCOResult:
    """车队级多车型组合替换的综合 TCO 决策分析。"""

    total_replace_count: int
    total_delta_capex_yuan: float
    total_annual_opex_saving_yuan: float
    total_annual_energy_saving_yuan: float
    total_annual_maint_saving_yuan: float
    overall_payback_period_years: Optional[float]
    total_annual_co2_reduction_t: float
    total_lifespan_co2_reduction_t: float
    overall_mac_yuan_per_tco2e: Optional[float]
    total_lifespan_net_savings_yuan: float
    by_vehicle_type: Dict[str, SingleVehicleTCOResult] = field(default_factory=dict)
    yearly_cashflow: List[float] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """转换为前端和 API 使用的字典结构。"""
        return {
            "total_replace_count": self.total_replace_count,
            "total_delta_capex_yuan": round(self.total_delta_capex_yuan, 2),
            "total_delta_capex_wan": round(self.total_delta_capex_yuan / 10000.0, 2),
            "total_annual_opex_saving_yuan": round(self.total_annual_opex_saving_yuan, 2),
            "total_annual_opex_saving_wan": round(self.total_annual_opex_saving_yuan / 10000.0, 2),
            "total_annual_energy_saving_yuan": round(self.total_annual_energy_saving_yuan, 2),
            "total_annual_maint_saving_yuan": round(self.total_annual_maint_saving_yuan, 2),
            "overall_payback_period_years": (
                round(self.overall_payback_period_years, 2)
                if self.overall_payback_period_years is not None
                else None
            ),
            "total_annual_co2_reduction_t": round(self.total_annual_co2_reduction_t, 2),
            "total_lifespan_co2_reduction_t": round(self.total_lifespan_co2_reduction_t, 2),
            "overall_mac_yuan_per_tco2e": (
                round(self.overall_mac_yuan_per_tco2e, 2)
                if self.overall_mac_yuan_per_tco2e is not None
                else None
            ),
            "total_lifespan_net_savings_yuan": round(self.total_lifespan_net_savings_yuan, 2),
            "total_lifespan_net_savings_wan": round(self.total_lifespan_net_savings_yuan / 10000.0, 2),
            "yearly_cashflow": [round(val, 2) for val in self.yearly_cashflow],
            "by_vehicle_type": {
                k: {
                    "replace_count": v.replace_count,
                    "annual_km": v.annual_km,
                    "delta_capex_yuan": round(v.delta_capex_total_yuan, 2),
                    "annual_opex_saving_yuan": round(v.annual_opex_saving_total_yuan, 2),
                    "payback_period_years": (
                        round(v.payback_period_years, 2)
                        if v.payback_period_years is not None
                        else None
                    ),
                    "mac_yuan_per_tco2e": (
                        round(v.mac_yuan_per_tco2e, 2)
                        if v.mac_yuan_per_tco2e is not None
                        else None
                    ),
                    "annual_co2_reduction_t": round(v.annual_co2_reduction_t, 2),
                    "baas_capex_note": v.baas_capex_note,
                }
                for k, v in self.by_vehicle_type.items()
            },
        }


def get_tco_benchmark(vehicle_type: str) -> Optional[VehicleTCOBenchmark]:
    """获取指定车型的 TCO 基准参数。"""
    if vehicle_type in DEFAULT_TCO_BENCHMARKS:
        return DEFAULT_TCO_BENCHMARKS[vehicle_type]
    for key, spec in DEFAULT_TCO_BENCHMARKS.items():
        if key in vehicle_type or vehicle_type in key:
            return spec
    return None


def calculate_single_vehicle_tco(
    vehicle_type: str,
    replace_count: int,
    annual_km: float,
    annual_co2_reduction_t: float,
    custom_benchmark: Optional[VehicleTCOBenchmark] = None,
    econ_params: Optional[TCOEconomicParameters] = None,
) -> SingleVehicleTCOResult:
    """计算单一车型替换为新能源车的 TCO 经济账与回收期。"""
    spec = custom_benchmark or get_tco_benchmark(vehicle_type)
    params = econ_params or TCOEconomicParameters()

    if spec is None or replace_count <= 0:
        return SingleVehicleTCOResult(
            target_vehicle_type=vehicle_type,
            replace_count=replace_count,
            annual_km=annual_km,
            delta_capex_total_yuan=0.0,
            delta_capex_per_vehicle_yuan=0.0,
            annual_fuel_cost_per_vehicle_yuan=0.0,
            annual_elec_cost_per_vehicle_yuan=0.0,
            annual_energy_saving_total_yuan=0.0,
            annual_maintenance_saving_total_yuan=0.0,
            annual_opex_saving_total_yuan=0.0,
            payback_period_years=None,
            mac_yuan_per_tco2e=None,
            annual_co2_reduction_t=annual_co2_reduction_t,
            lifespan_co2_reduction_t=annual_co2_reduction_t * params.lifespan_years,
            lifespan_net_savings_yuan=0.0,
            yearly_cumulative_cashflow_yuan=[0.0] * (params.lifespan_years + 1),
        )

    # 1. 初始投资增量 ΔCAPEX（元）
    # 若启用车电分离 (BaaS) 模式：剥离电池购置费，且无需自建昂贵专用重卡充电桩
    if params.is_baas_mode:
        # 若未指定立减金额，默认重卡立减20万，中卡立减10万，轻卡立减5万，微型立减2万
        default_chassis_discount = (
            params.baas_chassis_discount_wan
            if params.baas_chassis_discount_wan > 0
            else (20.0 if "重型" in vehicle_type else 10.0 if "中型" in vehicle_type else 5.0 if "轻型" in vehicle_type else 2.0)
        )
        single_capex_delta = (
            (spec.ev_vehicle_price_wan - default_chassis_discount - spec.ice_vehicle_price_wan)
            * 10000.0
        )
    else:
        single_capex_delta = (
            (spec.ev_vehicle_price_wan - spec.ice_vehicle_price_wan + spec.charger_cost_wan)
            * 10000.0
        )
    delta_capex_total = single_capex_delta * replace_count

    # 2. 燃料与电能单价确定
    fuel_price = (
        params.diesel_price_yuan_per_l
        if spec.fuel_type == "柴油"
        else params.gasoline_price_yuan_per_l
    )

    # 3. 单车年能耗成本计算
    single_annual_fuel_cost = (annual_km / 100.0) * spec.fuel_consumption_per_100km * fuel_price
    single_annual_elec_cost = (
        (annual_km / 100.0)
        * spec.electricity_consumption_per_100km
        * params.electricity_price_yuan_per_kwh
    )
    # 能耗节省可以为负：高电价下电车电费可能高于油费，此时真实结论是「更费钱」。
    # 早期用 max(0.0, ...) 截断会把负的能耗差悄悄抹平，只剩维保节省托底，
    # 于是明细里电费>油费、汇总里却仍报「省钱」，回收期被系统性低估。
    single_annual_energy_saving = single_annual_fuel_cost - single_annual_elec_cost

    # 4. 单车年维保与电池租赁成本计算
    single_annual_maint_saving = (
        spec.annual_maintenance_ice_yuan * spec.maintenance_saving_ratio
    )
    # 若为 BaaS 模式，需计入年电池租赁费作为额外 OPEX 支出 (冲减节省)
    single_annual_battery_rental = 0.0
    if params.is_baas_mode:
        single_annual_battery_rental = (
            params.baas_annual_battery_rental_yuan
            if params.baas_annual_battery_rental_yuan > 0
            else (45000.0 if "重型" in vehicle_type else 22000.0 if "中型" in vehicle_type else 12000.0 if "轻型" in vehicle_type else 5000.0)
        )

    # 5. 车队年运营节省 ΔOPEX（元/年）
    # ΔOPEX = 能耗节省 + 维保节省 - 电池租赁费
    single_annual_opex_saving = single_annual_energy_saving + single_annual_maint_saving - single_annual_battery_rental
    annual_energy_saving_total = single_annual_energy_saving * replace_count
    annual_maint_saving_total = single_annual_maint_saving * replace_count
    annual_opex_saving_total = single_annual_opex_saving * replace_count

    # 6. 静态投资回收期 T_payback（年）
    payback_period: Optional[float] = None
    if annual_opex_saving_total > 0:
        payback_period = delta_capex_total / annual_opex_saving_total

    # 7. 全周期总减碳量与折现净现值计算
    lifespan_co2 = annual_co2_reduction_t * params.lifespan_years
    r = params.discount_rate
    n = params.lifespan_years

    # 折现系数求和: Σ [1 / (1+r)^t]
    if r > 0:
        annuity_factor = (1.0 - (1.0 + r) ** (-n)) / r
    else:
        annuity_factor = float(n)

    pv_opex_savings = annual_opex_saving_total * annuity_factor
    lifespan_net_savings = pv_opex_savings - delta_capex_total

    # 8. 单位吨碳减排边际成本 MAC (元/tCO2e)
    mac: Optional[float] = None
    if lifespan_co2 > 0:
        # MAC = (ΔCAPEX - PV(ΔOPEX)) / 全周期总减碳量
        mac = (delta_capex_total - pv_opex_savings) / lifespan_co2

    # 9. 0~N 年累计净现金流序列（未折现静态现金流，直观展现回本点）
    yearly_cashflow = [-delta_capex_total]
    for year in range(1, n + 1):
        yearly_cashflow.append(-delta_capex_total + year * annual_opex_saving_total)

    baas_capex_note = ""
    if params.is_baas_mode:
        # 买断单车增量 = (ev - ice) + charger；BaaS 单车增量 = (ev - ice) - discount。
        # 于是 BaaS 的"降幅"= (charger + discount) / (ev - ice + charger)，
        # 只与 benchmark 的车价与充电桩单价有关，与年租金、年里程、油价电价全都无关。
        # 实测重卡：charger 3 万、discount 20 万、ev-ice 30 万 → 69.7%。
        # 把它写成"垫资骤降 70%"会让人误以为是运营优化带来的，实际上改一下
        # charger_cost_wan 这个假设值就能让比例在 67.7%~71.4% 之间任意滑动。
        buyout_delta = (
            spec.ev_vehicle_price_wan - spec.ice_vehicle_price_wan + spec.charger_cost_wan
        )
        if buyout_delta > 0:
            cut_pct = (buyout_delta - single_capex_delta / 10000.0) / buyout_delta * 100
            baas_capex_note = (
                f"BaaS 初始垫资比买断低 {cut_pct:.1f}%，该比例由代数恒等式决定"
                f"（买断单价增量 = 车价差 {spec.ev_vehicle_price_wan - spec.ice_vehicle_price_wan:.1f} 万"
                f" + 充电桩 {spec.charger_cost_wan:.1f} 万；BaaS 单价增量 = 车价差 − 电池剥离立减 "
                f"{default_chassis_discount:.1f} 万），与电池租金、年里程、油价电价均无关。"
                f"引用此比例时应同时披露充电桩成本假设，它不是敏感性分析的结论。"
            )

    return SingleVehicleTCOResult(
        target_vehicle_type=vehicle_type,
        replace_count=replace_count,
        annual_km=annual_km,
        delta_capex_total_yuan=delta_capex_total,
        delta_capex_per_vehicle_yuan=single_capex_delta,
        annual_fuel_cost_per_vehicle_yuan=single_annual_fuel_cost,
        annual_elec_cost_per_vehicle_yuan=single_annual_elec_cost,
        annual_energy_saving_total_yuan=annual_energy_saving_total,
        annual_maintenance_saving_total_yuan=annual_maint_saving_total,
        annual_opex_saving_total_yuan=annual_opex_saving_total,
        payback_period_years=payback_period,
        mac_yuan_per_tco2e=mac,
        annual_co2_reduction_t=annual_co2_reduction_t,
        lifespan_co2_reduction_t=lifespan_co2,
        lifespan_net_savings_yuan=lifespan_net_savings,
        yearly_cumulative_cashflow_yuan=yearly_cashflow,
        baas_capex_note=baas_capex_note,
    )


def _merge_same_type_tco(
    prev: Optional[SingleVehicleTCOResult], new: SingleVehicleTCOResult
) -> SingleVehicleTCOResult:
    """把同一车型的多条替换记录合并成一条，量级与顶层车队合计保持一致。

    仅累加可加的金额与吨数；回收期、MAC 按合并后的现金流重算，
    避免把两条记录的比率简单相加。
    """
    if prev is None:
        return new

    replace_count = prev.replace_count + new.replace_count
    delta_capex = prev.delta_capex_total_yuan + new.delta_capex_total_yuan
    annual_energy = prev.annual_energy_saving_total_yuan + new.annual_energy_saving_total_yuan
    annual_maint = prev.annual_maintenance_saving_total_yuan + new.annual_maintenance_saving_total_yuan
    annual_opex = prev.annual_opex_saving_total_yuan + new.annual_opex_saving_total_yuan
    annual_co2 = prev.annual_co2_reduction_t + new.annual_co2_reduction_t
    lifespan_co2 = prev.lifespan_co2_reduction_t + new.lifespan_co2_reduction_t
    lifespan_net = prev.lifespan_net_savings_yuan + new.lifespan_net_savings_yuan

    payback = delta_capex / annual_opex if annual_opex > 0 else None
    # 与 calculate_single_vehicle_tco 同口径：PV(ΔOPEX) = 全周期净节省 + ΔCAPEX
    pv_opex = lifespan_net + delta_capex
    mac = (delta_capex - pv_opex) / lifespan_co2 if lifespan_co2 > 0 else None

    yearly = [
        -delta_capex + year * annual_opex for year in range(len(new.yearly_cumulative_cashflow_yuan))
    ]
    yearly[0] = -delta_capex

    return SingleVehicleTCOResult(
        target_vehicle_type=new.target_vehicle_type,
        replace_count=replace_count,
        annual_km=new.annual_km,
        delta_capex_total_yuan=delta_capex,
        delta_capex_per_vehicle_yuan=(
            (prev.delta_capex_per_vehicle_yuan * prev.replace_count
             + new.delta_capex_per_vehicle_yuan * new.replace_count) / replace_count
        ),
        annual_fuel_cost_per_vehicle_yuan=new.annual_fuel_cost_per_vehicle_yuan,
        annual_elec_cost_per_vehicle_yuan=new.annual_elec_cost_per_vehicle_yuan,
        annual_energy_saving_total_yuan=annual_energy,
        annual_maintenance_saving_total_yuan=annual_maint,
        annual_opex_saving_total_yuan=annual_opex,
        payback_period_years=payback,
        mac_yuan_per_tco2e=mac,
        annual_co2_reduction_t=annual_co2,
        lifespan_co2_reduction_t=lifespan_co2,
        lifespan_net_savings_yuan=lifespan_net,
        yearly_cumulative_cashflow_yuan=yearly,
    )


def calculate_fleet_tco(
    replacements: List[Dict[str, Any]],
    econ_params: Optional[TCOEconomicParameters] = None,
) -> FleetTCOResult:
    """计算整个车队新能源替换措施的综合 TCO 与投资决策。

    Args:
        replacements: [
            {
                "vehicle_type": "重型柴油货车",
                "replace_count": 10,
                "annual_km": 80000.0,
                "annual_co2_reduction_t": 701.6,
            }, ...
        ]
        econ_params: 通用宏观经济参数
    """
    params = econ_params or TCOEconomicParameters()
    total_replace = 0
    total_delta_capex = 0.0
    total_annual_opex = 0.0
    total_annual_energy = 0.0
    total_annual_maint = 0.0
    total_annual_co2 = 0.0
    by_type: Dict[str, SingleVehicleTCOResult] = {}

    for item in replacements:
        vtype = item["vehicle_type"]
        rcount = int(item.get("replace_count", 0))
        km = float(item.get("annual_km", 80000.0))
        co2_red = float(item.get("annual_co2_reduction_t", 0.0))

        if rcount <= 0:
            continue

        res = calculate_single_vehicle_tco(
            vehicle_type=vtype,
            replace_count=rcount,
            annual_km=km,
            annual_co2_reduction_t=co2_red,
            econ_params=params,
        )
        # 同一车型可能有多条记录（不同里程/满载率）。直接赋值会让后一条覆盖前一条，
        # 使 by_vehicle_type 只保留部分车辆，而顶层合计却是全量，同响应内自相矛盾。
        by_type[vtype] = _merge_same_type_tco(by_type.get(vtype), res)
        total_replace += rcount
        total_delta_capex += res.delta_capex_total_yuan
        total_annual_opex += res.annual_opex_saving_total_yuan
        total_annual_energy += res.annual_energy_saving_total_yuan
        total_annual_maint += res.annual_maintenance_saving_total_yuan
        total_annual_co2 += res.annual_co2_reduction_t

    overall_payback: Optional[float] = None
    if total_annual_opex > 0:
        overall_payback = total_delta_capex / total_annual_opex

    total_lifespan_co2 = total_annual_co2 * params.lifespan_years
    r = params.discount_rate
    n = params.lifespan_years

    if r > 0:
        annuity_factor = (1.0 - (1.0 + r) ** (-n)) / r
    else:
        annuity_factor = float(n)

    pv_total_opex = total_annual_opex * annuity_factor
    total_lifespan_net_savings = pv_total_opex - total_delta_capex

    overall_mac: Optional[float] = None
    if total_lifespan_co2 > 0:
        overall_mac = (total_delta_capex - pv_total_opex) / total_lifespan_co2

    # 全车队逐年累计现金流
    yearly_cashflow = [-total_delta_capex]
    for year in range(1, n + 1):
        yearly_cashflow.append(-total_delta_capex + year * total_annual_opex)

    return FleetTCOResult(
        total_replace_count=total_replace,
        total_delta_capex_yuan=total_delta_capex,
        total_annual_opex_saving_yuan=total_annual_opex,
        total_annual_energy_saving_yuan=total_annual_energy,
        total_annual_maint_saving_yuan=total_annual_maint,
        overall_payback_period_years=overall_payback,
        total_annual_co2_reduction_t=total_annual_co2,
        total_lifespan_co2_reduction_t=total_lifespan_co2,
        overall_mac_yuan_per_tco2e=overall_mac,
        total_lifespan_net_savings_yuan=total_lifespan_net_savings,
        by_vehicle_type=by_type,
        yearly_cashflow=yearly_cashflow,
    )
