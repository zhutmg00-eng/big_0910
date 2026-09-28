"""外购电间接排放 (Scope 2) 与运输周转量核算引擎

法规依据：
1. 生态环境部、国家统计局《关于发布2023年电力二氧化碳排放因子的公告》（公告 2025年 第47号）
   - 全国电力平均因子: 0.5306 kgCO2/kWh
   - 全国电力平均因子(扣除非化石电量): 0.6096 kgCO2/kWh
   - 全国化石能源电力因子: 0.8273 kgCO2/kWh
   - 31个省级电力平均因子与6大区域电网因子
2. 交通运输部《交通运输碳达峰实施方案》营运货运周转量碳强度指标 (gCO2/t·km)
"""
from dataclasses import dataclass
from typing import List, Dict, Optional, Union
from src.engine.calculator import VehicleGroupData, calculate_load_adjustment

# ============================================================
# 1. 2023年官方电网二氧化碳排放因子库 (kgCO2/kWh)
# ============================================================
GRID_EMISSION_FACTORS: Dict[str, float] = {
    # 全国及综合口径
    "全国平均": 0.5306,
    "全国平均(扣除非化石)": 0.6096,
    "全国化石电力": 0.8273,

    # 六大区域电网
    "华北区域": 0.6361,
    "东北区域": 0.5122,
    "华东区域": 0.5500,
    "华中区域": 0.5271,
    "西北区域": 0.5543,
    "南方区域": 0.4042,
    "西南区域": 0.2472,

    # 31个省/直辖市/自治区
    "北京": 0.5554,
    "天津": 0.6796,
    "河北": 0.6516,
    "山西": 0.6634,
    "内蒙古": 0.6479,
    "辽宁": 0.4878,
    "吉林": 0.4671,
    "黑龙江": 0.5229,
    "上海": 0.5737,
    "江苏": 0.5827,
    "浙江": 0.4974,
    "安徽": 0.6553,
    "福建": 0.4211,
    "江西": 0.5836,
    "山东": 0.6191,
    "河南": 0.5897,
    "湖北": 0.4044,
    "湖南": 0.4976,
    "广东": 0.4419,
    "广西": 0.4476,
    "海南": 0.3648,
    "重庆": 0.5581,
    "四川": 0.1564,
    "贵州": 0.5683,
    "云南": 0.1333,
    "陕西": 0.6335,
    "甘肃": 0.4471,
    "青海": 0.1796,
    "宁夏": 0.6187,
    "新疆": 0.6021,
}

# ============================================================
# 2. 车型耗电率 (kWh/km) 与标准额定载重 (吨/辆)
# ============================================================
VEHICLE_ENERGY_SPECS: Dict[str, Dict[str, float]] = {
    "新能源物流车": {
        "kwh_per_km": 0.35,      # 综合城配轻量纯电 (35 kWh/100km)
        "rated_payload_t": 2.0,   # 额定载重 2 吨
    },
    "轻型柴油货车": {
        "kwh_per_km": 0.32,      # 若改用纯电轻卡为 32 kWh/100km
        "rated_payload_t": 2.0,   # 额定载重 2 吨 (蓝牌轻卡)
    },
    "中型柴油货车": {
        "kwh_per_km": 0.55,      # 纯电中卡约为 55 kWh/100km
        "rated_payload_t": 8.0,   # 额定载重 8 吨 (黄牌两轴中卡)
    },
    "重型柴油货车": {
        "kwh_per_km": 1.50,      # 纯电重卡约为 150 kWh/100km (以电代油对标)
        "rated_payload_t": 25.0,  # 额定载重 25 吨 (三轴/六轴半挂)
    },
    "LNG重型货车": {
        "kwh_per_km": 1.50,
        "rated_payload_t": 25.0,  # 额定载重 25 吨
    },
    "微型汽油货车": {
        "kwh_per_km": 0.18,      # 纯电微面约为 18 kWh/100km
        "rated_payload_t": 0.8,   # 额定载重 0.8 吨
    },
}

@dataclass
class IndirectEmissionResult:
    """购电间接排放核算结果 (Scope 2)"""
    total_electricity_kwh: float          # 总耗电量 (kWh)
    indirect_emission_tco2: float         # 间接排放量 (tCO2e)
    emission_by_vehicle: Dict[str, Dict]   # 分车型电耗与间接排放
    grid_name: str                        # 使用的电网因子名称
    grid_factor: float                    # 电力排放因子 (kgCO2/kWh)
    electric_vehicle_count: int           # 纯电动车辆数

@dataclass
class FreightTurnoverResult:
    """运输周转量与碳强度核算结果"""
    total_turnover_tkm: float             # 总货物周转量 (吨公里, t·km)
    total_turnover_wan_tkm: float         # 总货物周转量 (万吨公里)
    scope1_intensity_g_per_tkm: float     # Scope 1 排放强度 (gCO2 / t·km)
    scope2_intensity_g_per_tkm: float     # Scope 2 排放强度 (gCO2 / t·km)
    total_intensity_g_per_tkm: float      # 综合排放强度 (gCO2 / t·km)
    turnover_by_type: Dict[str, Dict]     # 各车型周转量与强度明细

def get_grid_factor(grid_key: str = "全国平均", custom_factor: Optional[float] = None) -> float:
    """获取电网二氧化碳排放因子 (kgCO2/kWh)"""
    if custom_factor is not None and custom_factor >= 0:
        return float(custom_factor)
    return GRID_EMISSION_FACTORS.get(grid_key, GRID_EMISSION_FACTORS["全国平均"])

def calculate_indirect_emission(
    fleet: List[VehicleGroupData],
    grid_key: str = "全国平均",
    custom_factor: Optional[float] = None,
) -> IndirectEmissionResult:
    """
    计算车队纯电动车辆外购电力产生的 Scope 2 间接碳排放量
    """
    factor = get_grid_factor(grid_key, custom_factor)
    total_kwh = 0.0
    total_ev_count = 0
    emission_by_vehicle = {}

    for g in fleet:
        # 仅针对新能源物流车核算用电间接排放
        if g.vehicle_type == "新能源物流车":
            spec = VEHICLE_ENERGY_SPECS.get(g.vehicle_type, {"kwh_per_km": 0.35})
            kwh_rate = spec["kwh_per_km"]
            # 耗电量 = 车辆数 × 年均里程 × 单位里程耗电率
            group_kwh = g.count * g.annual_km * kwh_rate
            # 间接排放量 = 耗电量 × 电网排放因子 / 1000 (kg -> t)
            group_emission_t = (group_kwh * factor) / 1000.0

            total_kwh += group_kwh
            total_ev_count += g.count

            if g.vehicle_type in emission_by_vehicle:
                prev = emission_by_vehicle[g.vehicle_type]
                emission_by_vehicle[g.vehicle_type] = {
                    "count": prev["count"] + g.count,
                    "electricity_kwh": round(prev["electricity_kwh"] + group_kwh, 2),
                    "indirect_emission_tco2": round(prev["indirect_emission_tco2"] + group_emission_t, 2),
                    "kwh_per_km": kwh_rate,
                }
            else:
                emission_by_vehicle[g.vehicle_type] = {
                    "count": g.count,
                    "electricity_kwh": round(group_kwh, 2),
                    "indirect_emission_tco2": round(group_emission_t, 2),
                    "kwh_per_km": kwh_rate,
                }

    total_emission_t = (total_kwh * factor) / 1000.0
    return IndirectEmissionResult(
        total_electricity_kwh=round(total_kwh, 2),
        indirect_emission_tco2=round(total_emission_t, 2),
        emission_by_vehicle=emission_by_vehicle,
        grid_name=grid_key if custom_factor is None else f"自定义({custom_factor})",
        grid_factor=round(factor, 4),
        electric_vehicle_count=total_ev_count,
    )

def calculate_freight_turnover(
    fleet: List[VehicleGroupData],
    direct_emission_t: float,
    indirect_emission_t: float = 0.0,
) -> FreightTurnoverResult:
    """
    计算车队实际货物周转量 (吨公里) 及运输碳排放强度 (gCO2 / t·km)
    
    公式：
      单组周转量 = count × annual_km × rated_payload × load_factor (t·km)
      综合碳强度 = (direct_emission_t + indirect_emission_t) × 1,000,000 / total_tkm (gCO2/t·km)
    """
    total_tkm = 0.0
    turnover_by_type = {}

    for g in fleet:
        spec = VEHICLE_ENERGY_SPECS.get(g.vehicle_type, {"rated_payload_t": 2.0})
        payload = spec["rated_payload_t"]
        # 实际载重周转量 = 车辆数 × 行驶里程 × 额定载重 × 实际满载率
        group_tkm = g.count * g.annual_km * payload * g.load_factor
        total_tkm += group_tkm

        if g.vehicle_type in turnover_by_type:
            prev = turnover_by_type[g.vehicle_type]
            turnover_by_type[g.vehicle_type] = {
                "count": prev["count"] + g.count,
                "turnover_tkm": round(prev["turnover_tkm"] + group_tkm, 2),
                "rated_payload_t": payload,
            }
        else:
            turnover_by_type[g.vehicle_type] = {
                "count": g.count,
                "turnover_tkm": round(group_tkm, 2),
                "rated_payload_t": payload,
            }

    wan_tkm = total_tkm / 10000.0 if total_tkm > 0 else 0.0

    # 碳排放强度计算 (gCO2 / t·km)
    scope1_intensity = (direct_emission_t * 1_000_000.0 / total_tkm) if total_tkm > 0 else 0.0
    scope2_intensity = (indirect_emission_t * 1_000_000.0 / total_tkm) if total_tkm > 0 else 0.0
    total_intensity = scope1_intensity + scope2_intensity

    return FreightTurnoverResult(
        total_turnover_tkm=round(total_tkm, 2),
        total_turnover_wan_tkm=round(wan_tkm, 2),
        scope1_intensity_g_per_tkm=round(scope1_intensity, 2),
        scope2_intensity_g_per_tkm=round(scope2_intensity, 2),
        total_intensity_g_per_tkm=round(total_intensity, 2),
        turnover_by_type=turnover_by_type,
    )

# 兼容性别名
get_grid_emission_factor = get_grid_factor
calculate_scope2_emission = calculate_indirect_emission
calculate_turnover_and_intensity = calculate_freight_turnover
Scope2Result = IndirectEmissionResult
TurnoverIntensityResult = FreightTurnoverResult
