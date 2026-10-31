"""货主报告模式 API 路由：POST /api/shipper-report

面向货主 / CDP 范围 3 第 4 类（上游运输及配送）问卷的承运商碳排放披露汇总。
计算引擎与 CLI（scripts/cli_bridge.py）共用 src/engine/shipper_report.py。
"""
from typing import Any, Dict, List

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from src.api.main import verify_api_key
from src.engine.calculator import VehicleGroupData
from src.engine.shipper_report import build_shipper_report
from src.models.fleet import VehicleInput

router = APIRouter(prefix="/api", tags=["货主报告"])


class ShipperReportRequest(BaseModel):
    """货主报告生成请求"""
    fleet: List[VehicleInput] = Field(
        ...,
        min_length=1,
        description="车队车辆组清单（同车型多组将按车公里加权合并）",
    )
    reporter_name: str = Field(
        ...,
        min_length=1,
        max_length=120,
        description="承运商名称（写入报告抬头）",
    )
    reporting_year: int = Field(
        ...,
        ge=2000,
        le=2100,
        description="报告年度（排放所属年度）",
    )


@router.post("/shipper-report")
def build_shipper_report_endpoint(
    req: ShipperReportRequest,
    _auth: Any = Depends(verify_api_key),
) -> Dict[str, Any]:
    """生成可提交给货主 / CDP 范围 3 第 4 类问卷的碳排放披露汇总（含口径声明与区间披露）"""
    fleet_groups = [
        VehicleGroupData(
            vehicle_type=v.vehicle_type,
            count=v.count,
            annual_km=v.annual_km,
            load_factor=v.load_factor,
        )
        for v in req.fleet
    ]
    report = build_shipper_report(
        fleet_groups=fleet_groups,
        reporter_name=req.reporter_name.strip(),
        reporting_year=req.reporting_year,
    )
    return report.to_dict()
