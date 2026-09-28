"""碳排放计算引擎统一入口"""
from src.engine.emission_factors import (
    get_emission_factor,
    list_vehicle_types,
    get_all_factors,
)
from src.engine.calculator import (
    VehicleGroupData,
    CarbonBaselineResult,
    calculate_emission,
    calculate_load_adjustment,
)
from src.engine.quota import (
    estimate_quota_gap,
    QuotaGapResult,
    SIMULATION_BUDGET_BENCHMARK,
    DEFAULT_SCENARIO_REDUCTION_TARGET,
    build_simulation_budget_benchmarks,
    QUOTA_BENCHMARK,
)
from src.engine.carbon_price import (
    estimate_compliance_cost,
    load_carbon_price_data,
    calculate_price_stats,
)
from src.engine.indirect_emission import (
    get_grid_factor,
    get_grid_emission_factor,
    calculate_indirect_emission,
    calculate_scope2_emission,
    calculate_freight_turnover,
    calculate_turnover_and_intensity,
    IndirectEmissionResult,
    Scope2Result,
    FreightTurnoverResult,
    TurnoverIntensityResult,
    GRID_EMISSION_FACTORS,
    VEHICLE_ENERGY_SPECS,
)

__all__ = [
    "get_emission_factor",
    "list_vehicle_types",
    "get_all_factors",
    "VehicleGroupData",
    "CarbonBaselineResult",
    "calculate_emission",
    "calculate_load_adjustment",
    "estimate_quota_gap",
    "QuotaGapResult",
    "SIMULATION_BUDGET_BENCHMARK",
    "DEFAULT_SCENARIO_REDUCTION_TARGET",
    "build_simulation_budget_benchmarks",
    "QUOTA_BENCHMARK",
    "estimate_compliance_cost",
    "load_carbon_price_data",
    "calculate_price_stats",
    "get_grid_emission_factor",
    "calculate_scope2_emission",
    "calculate_turnover_and_intensity",
    "Scope2Result",
    "TurnoverIntensityResult",
    "GRID_EMISSION_FACTORS",
]
