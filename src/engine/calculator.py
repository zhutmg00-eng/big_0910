"""碳排放基线计算引擎

核心公式：
    E = Σ (n_i × d_i × EF_i × LF_i) / 1000

    其中:
      E    = 企业年度直接运营排放总量 (tCO2e/年)
      n_i  = 第i类车型车辆数量 (辆)
      d_i  = 第i类车型年均运营里程 (km/年)
      EF_i = 第i类车型基准CO₂排放因子 (kgCO₂/km)
      LF_i = 低满载率保守偏置系数: LF_i = 1 + α×(0.75 - l_i)  当 l_i < 0.75，否则 1.0

核算边界与 LF 的物理含义（务必与论文 3.2 节口径一致）：
    本引擎输出的是**车公里口径**的直接运营排放 (Scope 1, Tank-to-Wheel)。
    在车公里口径下，车辆每公里燃料消耗随总质量下降而下降，因此空驶车辆的
    kgCO₂/km 实际上低于满载车辆。LF_i 并不是在描述这一物理过程，而是一个
    **经验性保守偏置因子**：当车队平均吨位实载率低于基准阈值时，说明运力
    利用不充分，按吨公里折算的碳强度显著劣化；为避免用标准工况因子低估这
    类车队的排放，按偏离程度线性上浮车公里排放取值，使估算结果构成保守
    上限包络。α 由行业实载率区间（0.45~0.88）与台账复核误差共同标定，
    其取值区间与敏感性见 docs/sensitivity_report.md。

    LF 作用方向：l_i 越低 → LF_i 越大 → 估算排放越高（保守，不低估）。
    LF 的最大取值出现在 l_i = 0 时为 1 + 0.15×0.75 = 1.1125。
"""
from dataclasses import dataclass
from typing import List
from src.engine.emission_factors import get_emission_factor
from src.config import LOAD_FACTOR_ALPHA, LOAD_FACTOR_THRESHOLD


@dataclass
class VehicleGroupData:
    """车队子集（内部计算用）"""
    vehicle_type: str
    count: int
    annual_km: float
    load_factor: float = 0.75


@dataclass
class CarbonBaselineResult:
    """碳排放基线计算结果"""
    total_emission_t: float
    emission_by_type: dict
    total_vehicles: int


def calculate_load_adjustment(load_factor: float) -> float:
    """
    计算低满载率保守偏置系数 LF_i

    当吨位实载率低于 0.75 时，按偏离程度线性上浮车公里排放取值，
    使估算结果构成保守上限包络（防止低估）；实载率高于阈值时不做调整。

    注意：LF 是经验性保守偏置因子，不是对"空驶车辆每公里油耗更高"的
    物理建模（车公里口径下空驶油耗实际更低）。其物理依据是吨公里碳强度
    随实载率下降而劣化，而本引擎采用车公里口径核算，故需用 LF 抵消这一
    口径差异带来的系统性低估。详见模块 docstring 与论文 3.2 节。
    """
    if load_factor < LOAD_FACTOR_THRESHOLD:
        return 1 + LOAD_FACTOR_ALPHA * (LOAD_FACTOR_THRESHOLD - load_factor)
    return 1.0


def calculate_emission(fleet: List[VehicleGroupData]) -> CarbonBaselineResult:
    """
    计算企业年度碳排放基线

    Args:
        fleet: 企业车队分组列表

    Returns:
        CarbonBaselineResult: 碳排放基线结果

    Raises:
        ValueError: 当包含不支持的车型时
    """
    total_emission = 0.0
    emission_by_type = {}
    total_vehicles = 0

    for group in fleet:
        ef = get_emission_factor(group.vehicle_type)
        if ef is None:
            raise ValueError(f"不支持的车型: {group.vehicle_type}")

        # 满载率调整系数
        load_adjustment = calculate_load_adjustment(group.load_factor)

        # 分类排放量 = 车辆数 × 年均里程 × 排放因子(kg/km) × 满载率调整 / 1000 → 吨
        group_emission = (
            group.count
            * group.annual_km
            * ef["co2_kg_per_km"]
            * load_adjustment
            / 1000
        )

        if group.vehicle_type in emission_by_type:
            prev = emission_by_type[group.vehicle_type]
            new_emission = prev["排放量_tCO2"] + round(group_emission, 2)
            new_count = prev["车辆数"] + group.count
            emission_by_type[group.vehicle_type] = {
                "排放量_tCO2": round(new_emission, 2),
                "占比": 0.0,
                "车辆数": new_count,
                "单辆排放_tCO2": round(new_emission / new_count, 2) if new_count else 0,
                "排放因子_kg_per_km": ef["co2_kg_per_km"],
                "满载率调整系数": round(load_adjustment, 4),
                "燃料类型": ef["fuel_type"],
            }
        else:
            emission_by_type[group.vehicle_type] = {
                "排放量_tCO2": round(group_emission, 2),
                "占比": 0.0,  # 稍后计算
                "车辆数": group.count,
                "单辆排放_tCO2": round(group_emission / group.count, 2) if group.count else 0,
                "排放因子_kg_per_km": ef["co2_kg_per_km"],
                "满载率调整系数": round(load_adjustment, 4),
                "燃料类型": ef["fuel_type"],
            }

        total_emission += group_emission
        total_vehicles += group.count

    # 计算各车型排放占比
    if total_emission > 0:
        for vtype in emission_by_type:
            emission_by_type[vtype]["占比"] = round(
                emission_by_type[vtype]["排放量_tCO2"] / total_emission * 100, 1
            )

    return CarbonBaselineResult(
        total_emission_t=round(total_emission, 2),
        emission_by_type=emission_by_type,
        total_vehicles=total_vehicles,
    )
