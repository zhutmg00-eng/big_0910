"""运输周转量与碳强度 (Scope 2 / t·km) API 路由

为 dsh-plugin-carbon-asset 插件及外部系统提供 HTTP POST /api/turnover 接口，
与 scripts/cli_bridge.py 的 turnover 命令共用同一套底层计算引擎。
"""
from dataclasses import asdict
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.api.main import verify_api_key
from src.engine.calculator import VehicleGroupData
from src.engine.indirect_emission import (
    calculate_scope2_emission,
    calculate_turnover_and_intensity,
)
from src.models.fleet import VehicleInput

router = APIRouter(prefix="/api", tags=["周转量与碳强度"])


class TurnoverRequest(BaseModel):
    """运输周转量与间接排放核算请求"""
    fleet: List[VehicleInput] = Field(
        ...,
        min_length=1,
        description="车队车辆组清单",
    )
    region: str = Field(
        default="全国",
        description="所属省份或电网区域（匹配官方电网排放因子）",
    )
    green_electricity_ratio: float = Field(
        default=0.0,
        ge=0.0,
        le=1.0,
        description="绿电交易比例（0.0~1.0）",
    )


@router.post("/turnover")
def calculate_turnover_endpoint(
    req: TurnoverRequest,
    _auth: Any = Depends(verify_api_key),
) -> Dict[str, Any]:
    """核算车队的运输周转量 (t·km)、Scope 2 间接排放及综合碳强度"""
    fleet_groups = [
        VehicleGroupData(
            vehicle_type=v.vehicle_type,
            count=v.count,
            annual_km=v.annual_km,
            load_factor=v.load_factor,
        )
        for v in req.fleet
    ]
    scope2_res = calculate_scope2_emission(
        fleet=fleet_groups,
        region_or_province=req.region,
        green_electricity_ratio=req.green_electricity_ratio,
    )
    turnover_res = calculate_turnover_and_intensity(
        fleet=fleet_groups,
        scope2_emission_t=scope2_res.scope2_emission_t,
    )
    return {
        "scope2": asdict(scope2_res),
        "turnover_and_intensity": asdict(turnover_res),
    }
