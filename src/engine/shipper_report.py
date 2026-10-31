"""货主报告模式：面向货主 / CDP 范围 3 第 4 类问卷的承运商碳排放披露汇总。

需求依据（2026-10 调研核实，见 docs/意义侧证据链.md）：
1. 中办、国办《有效降低全社会物流成本行动方案》（2024-11）第（十五）条：
   "支持开展物流领域碳排放核算及相关认证工作，构建物流碳排放计算公共服务平台"。
2. CDP 供应链问卷与财政部《企业可持续披露准则——第 1 号：气候（试行）》附录：
   运输排放计入采购方**范围 3 第 4 类（上游运输及配送）**。
3. 市场空档：京碳惠/丰和均面向货主，面向独立中小承运商的自助工具缺位。

口径与边界（必须随报告一起输出，不得截断）：
- 核算方法：活动水平法（车公里口径），E = Σ n·d·EF·LF / 1000，TTW 直接排放（范围 1）；
- 排放因子：与主引擎同一张因子表（data/raw/emission_factors.csv，来源逐行标注）；
  燃料换算系数按 GB 30510-2024 第 5.6 条（柴油 2.600 / 汽油 2.370 kg CO₂/L）；
- 区间披露：无台账输入的误差包络约 −26%~+29%（docs/small_fleet_envelope.md），
  报告给出区间参考而非精度承诺；
- 本报告为科研原型输出，**不构成第三方核查结论**，不用于履约或交易。
"""
from dataclasses import asdict, dataclass, field
from datetime import date
from typing import Any, Dict, List

from src.engine.calculator import VehicleGroupData, calculate_emission
from src.engine.indirect_emission import calculate_freight_turnover

# 无台账输入误差包络（docs/small_fleet_envelope.md：里程 ±25%、满载率受 LF 值域约束）
ENVELOPE_LOW_PCT = -26.0
ENVELOPE_HIGH_PCT = 29.0

FACTOR_SOURCES = [
    "《中国环境科学》2021, 41(7): 3122-3130（吕晨、蔡博峰等，分省道路运输 CO2 排放因子，TTW）",
    "GB 30510-2024《重型商用车辆燃料消耗量限值》第四阶段限值 × 第 5.6 条 KCO2（参考档）",
    "GB 30510-2018 第三阶段限值折算（旧标参考档）",
]
CONVERSION_NOTE = (
    "燃料台账换算系数：柴油 2.600 kg CO2/L、汽油 2.370 kg CO2/L（GB 30510-2024 第 5.6 条，"
    "与 GB/T 2589-2020 低位发热量 × 含碳量 × 碳氧化率推导值一致）；LNG 2.690 kg CO2/kg（IPCC 2006）。"
)

DISCLAIMERS = [
    "本报告由科研原型系统生成，核算结果未经第三方核查，不构成鉴证结论。",
    "排放为 TTW 直接排放（范围 1）；新能源车直接排放记为零，购电间接排放（范围 2）未计入本表，需另行核算。",
    "输入为用户填报的活动数据（车型/数量/年均里程/实载率），无逐车燃料台账时结果按区间理解。",
    "本报告不涉及碳配额履约、碳资产交易或减排量买卖。",
]
# 报告必须携带的最少免责声明条数（守卫用，防止后续迭代悄悄删减边界声明）
DISCLAIMER_COUNT_MIN = len(DISCLAIMERS)


@dataclass
class ShipperReport:
    """货主报告：单车队年度碳排放披露汇总（CDP 范围 3 第 4 类口径）。"""

    reporter_name: str
    reporting_year: int
    generated_at: str
    fleet_summary: List[Dict[str, Any]]
    total_scope1_tco2: float
    total_turnover_wan_tkm: float
    intensity_g_per_tkm: float
    disclosure_interval: Dict[str, Any]
    methodology: Dict[str, Any]
    cdp_mapping: Dict[str, Any]
    disclaimers: List[str] = field(default_factory=lambda: list(DISCLAIMERS))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def build_shipper_report(
    fleet_groups: List[VehicleGroupData],
    reporter_name: str,
    reporting_year: int,
) -> ShipperReport:
    """按 CDP 范围 3 第 4 类（上游运输及配送）的报告口径汇总单车队排放。"""
    if not fleet_groups:
        raise ValueError("车队为空，无法生成货主报告")
    if reporting_year < 2000 or reporting_year > 2100:
        raise ValueError("报告年度不合理")

    baseline = calculate_emission(fleet_groups)
    turnover = calculate_freight_turnover(fleet_groups)
    total = baseline.total_emission_t

    # 同一车型多组输入会被引擎按车公里加权合并；报告采用合并后的权威分车型结果
    fleet_summary: List[Dict[str, Any]] = []
    for vtype, item in baseline.emission_by_type.items():
        fleet_summary.append(
            {
                "vehicle_type": vtype,
                "count": item["车辆数"],
                "vehicle_km_wan": item["车公里_万km"],
                "emission_tco2": item["排放量_tCO2"],
                "share_pct": item["占比"],
                "emission_factor_kg_per_km": item["排放因子_kg_per_km"],
                "load_factor_adjustment": item["满载率调整系数"],
                "fuel_type": item["燃料类型"],
            }
        )

    return ShipperReport(
        reporter_name=reporter_name,
        reporting_year=reporting_year,
        generated_at=date.today().isoformat(),
        fleet_summary=fleet_summary,
        total_scope1_tco2=round(total, 2),
        total_turnover_wan_tkm=round(turnover.total_turnover_wan_tkm, 1),
        intensity_g_per_tkm=round(turnover.total_intensity_g_per_tkm, 2),
        disclosure_interval={
            "lower_pct": ENVELOPE_LOW_PCT,
            "upper_pct": ENVELOPE_HIGH_PCT,
            "note": (
                "无台账输入下的误差包络（里程 ±25%、满载率经 LF 值域约束），"
                "点值应按区间理解；优先补实测里程可显著收窄区间"
                "（要控在 ±10% 内里程需准到 ±6%~7%）。"
            ),
        },
        methodology={
            "method": "活动水平法（车公里口径）",
            "formula": "E = Σ (车辆数 × 年均里程 × 排放因子 × 满载率调整系数) / 1000",
            "scope": "TTW 直接排放（范围 1）",
            "factor_sources": FACTOR_SOURCES,
            "conversion_note": CONVERSION_NOTE,
            "load_factor_note": (
                "LF 为低满载率保守偏置系数（LF = 1 + 0.15×(0.75−l)，l<0.75 时生效），"
                "用于低实载率场景不低估，非物理油耗模型。"
            ),
        },
        cdp_mapping={
            "purchaser_scope": "范围 3",
            "category_no": 4,
            "category_name": "上游运输及配送（Upstream transportation and distribution）",
            "policy_reference": [
                "CDP 供应链问卷（运输排放计入采购方范围 3 第 4 类）",
                "财政部《企业可持续披露准则——第 1 号：气候（试行）》附录类别 4",
            ],
            "data_quality": "初级活动数据（承运商填报）+ 缺省排放因子（default），未做数据质量评分",
        },
    )
