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
