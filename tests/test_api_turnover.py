"""针对 POST /api/turnover 端点的接口测试 (GAP-1 修复验证)"""
import sys
from pathlib import Path
from fastapi.testclient import TestClient
import pytest

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.api.main import app
from src.engine.calculator import VehicleGroupData
from src.engine.indirect_emission import (
    calculate_scope2_emission,
    calculate_turnover_and_intensity,
)

client = TestClient(app)


def test_turnover_endpoint_success_and_matches_engine():
    """验证 /api/turnover 能够成功计算，且与底层 engine 结果一致"""
    payload = {
        "fleet": [
            {
                "vehicle_type": "重型柴油货车",
                "count": 50,
                "annual_km": 80000.0,
                "load_factor": 0.85,
            },
            {
                "vehicle_type": "新能源物流车",
                "count": 10,
                "annual_km": 40000.0,
                "load_factor": 0.80,
            },
        ],
        "region": "广东",
        "green_electricity_ratio": 0.3,
    }
    # 1. 调 API
    r = client.post("/api/turnover", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()

    # 2. 验证关键字段结构
    assert "scope2" in data
    assert "turnover_and_intensity" in data
    scope2 = data["scope2"]
    turnover = data["turnover_and_intensity"]

    assert scope2["electric_vehicle_count"] == 10
    assert scope2["grid_name"] == "广东"
    assert turnover["total_turnover_tkm"] > 0
    assert turnover["total_intensity_g_per_tkm"] > 0

    # 3. 与 engine 底层计算比对
    fleet_groups = [
        VehicleGroupData(
            vehicle_type=v["vehicle_type"],
            count=v["count"],
            annual_km=v["annual_km"],
            load_factor=v["load_factor"],
        )
        for v in payload["fleet"]
    ]
    expected_s2 = calculate_scope2_emission(fleet=fleet_groups, region_or_province=payload["region"], green_electricity_ratio=payload["green_electricity_ratio"])
    expected_to = calculate_turnover_and_intensity(fleet_groups, scope2_emission_t=expected_s2.scope2_emission_t)

    assert scope2["indirect_emission_tco2"] == pytest.approx(expected_s2.indirect_emission_tco2, rel=1e-6)
    assert turnover["total_turnover_tkm"] == pytest.approx(expected_to.total_turnover_tkm, rel=1e-6)
    assert turnover["total_intensity_g_per_tkm"] == pytest.approx(expected_to.total_intensity_g_per_tkm, rel=1e-6)


def test_turnover_endpoint_input_validation():
    """验证输入边界校验：空车队拦截、绿电比例超界拦截"""
    # 1. 空车队 -> 422
    r_empty = client.post("/api/turnover", json={"fleet": []})
    assert r_empty.status_code == 422

    # 2. 绿电比例 > 1.0 -> 422
    r_ratio = client.post("/api/turnover", json={
        "fleet": [{"vehicle_type": "重型柴油货车", "count": 10, "annual_km": 50000.0, "load_factor": 0.7}],
        "green_electricity_ratio": 1.5,
    })
    assert r_ratio.status_code == 422
