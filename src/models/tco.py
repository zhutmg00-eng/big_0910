"""TCO 投资决策数据模型。"""

from __future__ import annotations

from typing import Optional
from pydantic import BaseModel, Field


class VehicleTCORunRequest(BaseModel):
    """单个或多个车型 TCO 测算请求。"""

    vehicle_type: str = Field(..., description="目标燃油车型名称")
    replace_count: int = Field(..., gt=0, description="替换车辆数")
    annual_km: float = Field(..., gt=0, description="年均运营里程 (km)")
    annual_co2_reduction_t: float = Field(0.0, ge=0, description="年碳减排量 (tCO2e)")
    diesel_price_yuan_per_l: Optional[float] = Field(None, gt=0, description="自定义柴油价格")
    electricity_price_yuan_per_kwh: Optional[float] = Field(None, gt=0, description="自定义综合电价")
    ev_vehicle_price_wan: Optional[float] = Field(None, gt=0, description="自定义新能源车单价(万元)")
    lifespan_years: Optional[int] = Field(5, ge=1, le=15, description="评估运营周期(年)")
    # 车电分离（BaaS）模式。缺这三项时 API 只能算买断口径，
    # 而项目对外主打的「初始垫资降 70%」正是 BaaS 口径——静默忽略会让
    # 调用方拿到买断的 delta_capex 却以为是 BaaS 的，属于最危险的一类静默错误。
    is_baas_mode: bool = Field(False, description="是否启用换电车电分离(BaaS)模式")
    baas_chassis_discount_wan: Optional[float] = Field(
        None, ge=0, description="剥离动力电池后的单车购置立减(万元/车)；留空按车型内置档位")
    baas_annual_battery_rental_yuan: Optional[float] = Field(
        None, ge=0, description="单车年电池租赁费(元/年/车)；留空按车型内置档位")
