"""直接运营排放与模拟碳预算数据模型。"""
from pydantic import BaseModel, Field
from typing import Optional


class CarbonBaseline(BaseModel):
    """碳排放基线计算结果"""
    total_emission_t: float = Field(..., description="年度直接运营排放总量 (tCO2e)")
    emission_by_type: dict = Field(default_factory=dict, description="分车型排放明细")
    total_vehicles: int = Field(..., description="总车辆数")


class CarbonBudget(BaseModel):
    """模拟碳预算差额结果。"""

    total_budget_t: float = Field(..., description="模拟碳预算总量 (tCO2e)")
    total_emission_t: float = Field(..., description="直接运营排放 (tCO2e)")
    gap_t: float = Field(..., description="差额（正=超出预算，负=低于预算）")
    status: str = Field(..., description="状态：超出预算/低于预算/基本平衡")


class ScenarioCost(BaseModel):
    """碳价对标情景金额。"""

    judgement: str = Field(..., description="情景判断")
    gap_t: Optional[float] = Field(None, description="模拟碳预算差额")
    current_price: Optional[float] = Field(None, description="当前碳价")
    avg_price_90d: Optional[float] = Field(None, description="近90日均价")
    cost_estimate: Optional[float] = Field(None, description="情景成本参考值")
    cost_low: Optional[float] = Field(None, description="成本下限")
    cost_high: Optional[float] = Field(None, description="成本上限")
    notes: Optional[str] = Field(None, description="备注")


class CarbonResult(BaseModel):
    """完整碳排放计算结果"""
    company_name: str = Field(..., description="企业名称")
    total_emission_t: float = Field(..., description="年度直接运营排放总量 (tCO2e)")
    total_vehicles: int = Field(..., description="车队总车辆数")
    emission_by_type: dict = Field(default_factory=dict, description="分车型排放明细")
    carbon_budget: dict = Field(default_factory=dict, description="模拟碳预算分析结果")
    scenario_cost: dict = Field(default_factory=dict, description="碳价对标情景金额分析结果")
    methodology_note: str = Field(..., description="方法学说明与口径声明")


# 兼容早期导入名称；新代码应使用 CarbonBudget 和 ScenarioCost。
QuotaGap = CarbonBudget
ComplianceCost = ScenarioCost
