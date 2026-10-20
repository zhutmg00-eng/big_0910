"""不确定性分析请求模型。"""
from typing import Literal

from pydantic import BaseModel, Field

from src.models.fleet import VehicleInput


class UncertaintyRequest(BaseModel):
    fleet: list[VehicleInput] = Field(..., min_length=1, description="车队分组列表")
    n_samples: int = Field(10000, ge=100, le=200000, description="蒙特卡洛抽样次数")
    seed: int = Field(2026, description="随机种子（保证结果可复现）")
    data_quality: Literal["台账", "抽样", "估计"] = Field(
        "抽样", description="活动数据质量等级：台账(CV 5%)/抽样(CV 10%)/估计(CV 20%)"
    )
    load_delta: float = Field(0.05, ge=0, le=0.3, description="满载率均匀分布半宽")
