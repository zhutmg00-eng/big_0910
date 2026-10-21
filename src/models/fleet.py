"""API 共用的车队输入模型。"""

from pydantic import BaseModel, Field, field_validator

from src.engine.emission_factors import get_emission_factor

#: 单一车型分组的车辆数上限。10 万辆已经超过绝大多数物流企业自有车队规模
#: （验证案例里最大的顺丰也只有 27,500 辆），再大就是数量级笔误。
MAX_FLEET_COUNT = 100_000
#: 单车年运营里程上限。长途干线重卡年跑 15~20 万 km 属高强度，30 万 km
#: 意味着平均每天 820 km、全年无休，已到物理与法规极限。
MAX_ANNUAL_KM = 300_000.0


class VehicleInput(BaseModel):
    """一组同类型车辆。"""

    vehicle_type: str = Field(..., min_length=1, description="车型名称")
    # 上界不是「防攻击」，而是防把吨/台/公里数填错列：第 8 轮评审把
    # count=10**6、annual_km=1e12 直接送进来，接口返回 200 与
    # total_emission_t=8.77e14，界面上没有任何提示。全国营运货车保有量也就
    # 千万级、单车年里程 30 万 km 已是极端，超过这个量级只会是笔误。
    count: int = Field(
        ..., gt=0, le=MAX_FLEET_COUNT,
        description=f"车辆数量（辆），上限 {MAX_FLEET_COUNT}",
    )
    annual_km: float = Field(
        ..., gt=0, le=MAX_ANNUAL_KM,
        description=f"年均运营里程 (km/年)，上限 {MAX_ANNUAL_KM:,.0f}",
    )
    load_factor: float = Field(0.75, ge=0, le=1, description="平均满载率 (0~1)")

    @field_validator("vehicle_type")
    @classmethod
    def validate_vehicle_type(cls, value: str) -> str:
        vehicle_type = value.strip()
        if not get_emission_factor(vehicle_type):
            raise ValueError(f"不支持的车型: {vehicle_type or value}")
        return vehicle_type


class FleetInput(BaseModel):
    """企业车队输入。"""

    company_name: str = Field(..., min_length=1, max_length=100, description="企业名称")
    fleet: list[VehicleInput] = Field(..., min_length=1, description="车队分组列表")
    scenario_reduction_target: float = Field(
        0.10,
        ge=0,
        lt=1,
        description="模拟预算相对参考活动排放的减排目标（科研情景参数）",
    )

    @field_validator("company_name")
    @classmethod
    def normalize_company_name(cls, value: str) -> str:
        company_name = value.strip()
        if not company_name:
            raise ValueError("企业名称不能为空")
        return company_name


# 兼容早期代码中的名称。
VehicleGroup = VehicleInput
