"""多企业对比 API 测试"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


class TestCompareAPI:
    def test_compare_enterprises_success(self):
        """测试两个企业对比计算与排序"""
        payload = {
            "companies": [
                {
                    "company_name": "A物流公司",
                    "fleet": [
                        {"vehicle_type": "重型柴油货车", "count": 50, "annual_km": 80000, "load_factor": 0.70},
                        {"vehicle_type": "轻型柴油货车", "count": 30, "annual_km": 30000, "load_factor": 0.75},
                    ],
                },
                {
                    "company_name": "B物流公司",
                    "fleet": [
                        {"vehicle_type": "重型柴油货车", "count": 20, "annual_km": 80000, "load_factor": 0.75},
                        {"vehicle_type": "新能源物流车", "count": 30, "annual_km": 40000, "load_factor": 0.75},
                    ],
                },
            ]
        }
        response = client.post("/api/compare", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert len(data["comparison"]) == 2
        assert len(data["ranking_by_emission"]) == 2
        assert "A物流公司" in data["ranking_by_emission"]
        assert "B物流公司" in data["ranking_by_emission"]
        # A公司的排放应高于B公司
        assert data["ranking_by_emission"][0] == "A物流公司"
        assert data["summary"]["企业数量"] == 2
        assert data["summary"]["直接运营排放总量_tCO2e"] > 0
        assert "carbon_budget_t" in data["comparison"][0]
        assert "scenario_cost" in data["comparison"][0]

    def test_compare_less_than_two_companies(self):
        """少于2个企业时应返回422或400验证错误"""
        payload = {
            "companies": [
                {
                    "company_name": "单个企业",
                    "fleet": [{"vehicle_type": "重型柴油货车", "count": 10, "annual_km": 50000}],
                }
            ]
        }
        response = client.post("/api/compare", json=payload)
        assert response.status_code in (400, 422)

    def test_compare_rejects_invalid_nested_vehicle(self):
        payload = {
            "companies": [
                {
                    "company_name": "A企业",
                    "fleet": [{"vehicle_type": "重型柴油货车", "count": -1, "annual_km": 50000}],
                },
                {
                    "company_name": "B企业",
                    "fleet": [{"vehicle_type": "未知车型", "count": 1, "annual_km": 50000}],
                },
            ]
        }
        response = client.post("/api/compare", json=payload)
        assert response.status_code == 422
