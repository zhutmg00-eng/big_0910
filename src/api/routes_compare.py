"""多企业直接运营排放与减排情景对比 API 路由

提供多企业并排对比功能，输入多个企业车队数据，输出：
- 排放总量对比
- 模拟碳预算差额对比
- 情景成本对比及排序

所有计算复用 engine 层现有引擎。
"""
from fastapi import APIRouter, Depends
from typing import List
from pydantic import BaseModel, Field

from src.api.main import verify_api_key
from src.models.fleet import FleetInput

router = APIRouter(prefix="/api", tags=["多企业对比"])


# ============================================================
# 请求/响应模型
# ============================================================

class CompareFleetInput(FleetInput):
    """对比用企业车队输入"""


class CompareRequest(BaseModel):
    """多企业对比请求"""
    companies: List[CompareFleetInput] = Field(
        ...,
        min_length=2,
        description="至少2个企业车队数据"
    )


class EnterpriseCompareResult(BaseModel):
    """单个企业的对比结果"""
    company_name: str
    total_emission_t: float
    total_vehicles: int
    emission_by_type: dict
    carbon_budget_t: float
    budget_gap_t: float
    budget_status: str
    budget_reduction_target: float
    scenario_cost: dict


class CompareResponse(BaseModel):
    """多企业对比响应"""
    comparison: List[EnterpriseCompareResult]
    ranking_by_emission: List[str]  # 按排放降序排列的企业名
    ranking_by_gap: List[str]  # 按模拟碳预算差额降序排列的企业名
    ranking_by_cost: List[str]  # 按情景成本降序排列的企业名
    summary: dict  # 汇总统计


# ============================================================
# API 路由
# ============================================================

@router.post("/compare", response_model=CompareResponse)
def compare_enterprises(
    request: CompareRequest,
    api_key: str = Depends(verify_api_key),
):
    """
    对比多个企业的直接运营排放与模拟减排情景数据

    输入多个企业车队数据，输出并排对比：
    - 排放总量、模拟碳预算差额、情景成本
    - 多维度排序（排放量、预算差额、情景成本）
    - 汇总统计

    示例请求：
        POST /api/compare
        {
            "companies": [
                {
                    "company_name": "A物流公司",
                    "fleet": [
                        {"vehicle_type": "重型柴油货车", "count": 50, "annual_km": 80000, "load_factor": 0.7},
                        {"vehicle_type": "轻型柴油货车", "count": 30, "annual_km": 30000}
                    ]
                },
                {
                    "company_name": "B物流公司",
                    "fleet": [
                        {"vehicle_type": "重型柴油货车", "count": 30, "annual_km": 80000},
                        {"vehicle_type": "新能源物流车", "count": 20, "annual_km": 40000}
                    ]
                }
            ]
        }
    """
    from src.engine.calculator import VehicleGroupData, calculate_emission
    from src.engine.quota import estimate_quota_gap
    from src.engine.carbon_price import estimate_compliance_cost, load_carbon_price_data

    # 加载碳价数据（所有企业共用同一碳价）
    price_df = load_carbon_price_data()

    results = []
    for company in request.companies:
        # 1. 转换输入为内部格式
        fleet = []
        fleet_summary = {}
        for v in company.fleet:
            vehicle_data = VehicleGroupData(
                vehicle_type=v.vehicle_type,
                count=v.count,
                annual_km=v.annual_km,
                load_factor=v.load_factor,
            )
            fleet.append(vehicle_data)
            fleet_summary[v.vehicle_type] = fleet_summary.get(v.vehicle_type, 0) + v.count

        # 2. 计算碳排放
        baseline = calculate_emission(fleet)

        # 3. 估算模拟碳预算差额
        gap = estimate_quota_gap(
            baseline.total_emission_t,
            fleet_summary,
            reduction_target=company.scenario_reduction_target,
        )

        # 4. 估算碳价对标情景成本
        cost = estimate_compliance_cost(gap.gap_t, price_df)

        results.append(EnterpriseCompareResult(
            company_name=company.company_name,
            total_emission_t=baseline.total_emission_t,
            total_vehicles=baseline.total_vehicles,
            emission_by_type=baseline.emission_by_type,
            carbon_budget_t=gap.total_quota_t,
            budget_gap_t=gap.gap_t,
            budget_status=gap.gap_status,
            budget_reduction_target=gap.reduction_target,
            scenario_cost=cost,
        ))

    # 多维度排序
    ranking_emission = sorted(results, key=lambda x: x.total_emission_t, reverse=True)
    ranking_gap = sorted(results, key=lambda x: x.budget_gap_t, reverse=True)

    # 按碳价对标情景成本排序
    def cost_key(r: EnterpriseCompareResult) -> float:
        cost_val = r.scenario_cost.get("情景成本_参考价", 0)
        return cost_val if cost_val > 0 else -1

    ranking_cost = sorted(results, key=cost_key, reverse=True)

    # 汇总统计
    total_emission = sum(r.total_emission_t for r in results)
    total_gap = sum(r.budget_gap_t for r in results)
    total_cost = sum(
        r.scenario_cost.get("情景成本_参考价", 0)
        for r in results
        if r.scenario_cost.get("情景成本_参考价", 0) > 0
    )

    summary = {
        "企业数量": len(results),
        "直接运营排放总量_tCO2e": round(total_emission, 2),
        "总预算差额_tCO2e": round(total_gap, 2),
        "总情景成本_元": round(total_cost, 2),
        "排放最高企业": ranking_emission[0].company_name if ranking_emission else "",
        "缺口最大企业": ranking_gap[0].company_name if ranking_gap else "",
    }

    return CompareResponse(
        comparison=results,
        ranking_by_emission=[r.company_name for r in ranking_emission],
        ranking_by_gap=[r.company_name for r in ranking_gap],
        ranking_by_cost=[r.company_name for r in ranking_cost],
        summary=summary,
    )
