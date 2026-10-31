"""货主报告模式（shipper report）引擎与 API 测试。

覆盖：
1. 引擎：总量与主引擎一致、分车型合并与占比、口径声明与免责声明齐全、区间披露、CDP 映射；
2. API：成功路径、同车型合并、输入校验 422、无效车型 422。
"""
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.api.main import app
from src.engine.calculator import VehicleGroupData, calculate_emission
from src.engine.shipper_report import (
    DISCLAIMER_COUNT_MIN,
    build_shipper_report,
)

client = TestClient(app)


def _fleet():
    return [
        VehicleGroupData("重型柴油货车", 20, 80000, 0.85),
        VehicleGroupData("轻型柴油货车", 10, 30000, 0.70),
        VehicleGroupData("新能源物流车", 5, 28000, 0.72),
    ]


def test_report_totals_match_engine():
    """报告总量必须与主引擎逐位一致，分车型占比合计 100%。"""
    fleet = _fleet()
    report = build_shipper_report(fleet, "某某物流有限公司", 2025)
    engine = calculate_emission(fleet)

    assert report.total_scope1_tco2 == engine.total_emission_t
    assert sum(row["emission_tco2"] for row in report.fleet_summary) == pytest.approx(
        report.total_scope1_tco2, abs=0.05
    )
    assert sum(row["share_pct"] for row in report.fleet_summary) == pytest.approx(100.0, abs=0.2)
    assert sum(row["count"] for row in report.fleet_summary) == engine.total_vehicles


def test_report_carries_methodology_and_disclaimers():
    """口径声明、因子来源、换算系数、免责声明、区间披露、CDP 映射必须齐全。"""
    report = build_shipper_report(_fleet(), "某某物流有限公司", 2025)

    methodology_text = repr(report.methodology)
    assert "活动水平法" in methodology_text
    assert "GB 30510-2024" in methodology_text and "2.600" in methodology_text
    assert "3122-3130" in methodology_text  # v1.1.0 修正后的论文页码

    assert len(report.disclaimers) >= DISCLAIMER_COUNT_MIN
    joined = " ".join(report.disclaimers)
    assert "未经第三方核查" in joined
    assert "范围 2" in joined  # 间接排放边界必须披露
    assert "不涉及碳配额履约" in joined

    assert report.disclosure_interval["lower_pct"] == -26.0
    assert report.disclosure_interval["upper_pct"] == 29.0
    assert "误差包络" in report.disclosure_interval["note"]

    assert report.cdp_mapping["category_no"] == 4
    assert "上游运输及配送" in report.cdp_mapping["category_name"]
    assert report.cdp_mapping["purchaser_scope"] == "范围 3"


def test_report_merges_same_vehicle_type():
    """同车型多组输入应合并为一行，排放与车公里按引擎合并口径。"""
    fleet = [
        VehicleGroupData("轻型柴油货车", 10, 30000, 0.70),
        VehicleGroupData("轻型柴油货车", 5, 36000, 0.58),
    ]
    report = build_shipper_report(fleet, "某某物流有限公司", 2025)
    assert len(report.fleet_summary) == 1
    assert report.fleet_summary[0]["count"] == 15


def test_report_rejects_bad_year():
    with pytest.raises(ValueError):
        build_shipper_report(_fleet(), "某某物流", 1900)


def test_shipper_report_endpoint_success():
    payload = {
        "fleet": [
            {"vehicle_type": "重型柴油货车", "count": 8, "annual_km": 120000.0, "load_factor": 0.85}
        ],
        "reporter_name": "测试承运商",
        "reporting_year": 2025,
    }
    resp = client.post("/api/shipper-report", json=payload)
    assert resp.status_code == 200
    body = resp.json()
    assert body["reporter_name"] == "测试承运商"
    assert body["cdp_mapping"]["category_no"] == 4
    assert body["total_scope1_tco2"] > 0


def test_shipper_report_endpoint_validation():
    # 车队为空 → 422
    resp = client.post("/api/shipper-report", json={"fleet": [], "reporter_name": "x", "reporting_year": 2025})
    assert resp.status_code == 422
    # 无效车型 → 422
    resp = client.post(
        "/api/shipper-report",
        json={
            "fleet": [{"vehicle_type": "不存在的车型", "count": 1, "annual_km": 10000.0, "load_factor": 0.8}],
            "reporter_name": "x",
            "reporting_year": 2025,
        },
    )
    assert resp.status_code == 422
    # 年度越界 → 422
    resp = client.post(
        "/api/shipper-report",
        json={
            "fleet": [{"vehicle_type": "轻型柴油货车", "count": 1, "annual_km": 10000.0, "load_factor": 0.8}],
            "reporter_name": "x",
            "reporting_year": 1899,
        },
    )
    assert resp.status_code == 422
