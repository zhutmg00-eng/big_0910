"""DeepSeek Harness (dsh) CLI 桥接引擎单元测试。"""

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
PYTHON_EXE = sys.executable
CLI_SCRIPT = ROOT_DIR / "scripts" / "cli_bridge.py"


def run_bridge(cmd: str, payload: dict | None = None) -> tuple[int, dict, str]:
    args = [PYTHON_EXE, str(CLI_SCRIPT), cmd]
    if payload is not None:
        args.extend(["--json", json.dumps(payload, ensure_ascii=False)])

    env = {**os.environ, "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run(
        args,
        cwd=ROOT_DIR,
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=env,
    )
    if p.returncode == 0:
        return p.returncode, json.loads(p.stdout), p.stderr
    return p.returncode, {}, p.stderr


class TestCLIBridge:
    def test_vehicle_types(self):
        code, data, err = run_bridge("vehicle-types")
        assert code == 0
        assert "vehicle_types" in data
        assert "tco_benchmarks" in data
        assert len(data["vehicle_types"]) >= 5

    def test_calculate_command(self):
        payload = {
            "company_name": "测试物流企业",
            "fleet": [
                {
                    "vehicle_type": "重型柴油货车",
                    "count": 10,
                    "annual_km": 80000.0,
                    "load_factor": 0.75,
                }
            ],
            "scenario_reduction_target": 0.10,
        }
        code, data, err = run_bridge("calculate", payload)
        assert code == 0
        assert data["company_name"] == "测试物流企业"
        assert data["total_vehicles"] == 10
        assert data["total_emission_t"] > 0
        assert "carbon_budget" in data

    def test_tco_command(self):
        payload = {
            "vehicle_type": "重型柴油货车",
            "replace_count": 5,
            "annual_km": 80000.0,
            "annual_co2_reduction_t": 350.8,
        }
        code, data, err = run_bridge("tco", payload)
        assert code == 0
        assert data["target_vehicle_type"] == "重型柴油货车"
        assert data["replace_count"] == 5
        assert data["delta_capex_total_yuan"] > 0
        assert data["annual_opex_saving_total_yuan"] > 0
        assert data["payback_period_years"] is not None

    def test_reduction_command(self):
        payload = {
            "baseline_fleet": [
                {
                    "vehicle_type": "重型柴油货车",
                    "count": 50,
                    "annual_km": 80000.0,
                    "load_factor": 0.75,
                }
            ],
            "changes": {"替换为新能源物流车": 10},
        }
        code, data, err = run_bridge("reduction", payload)
        assert code == 0
        assert data["reduction_t"] > 0
        assert data["reduction_pct"] > 0
        assert "tco_analysis" in data

    def test_compare_command(self):
        payload = {
            "companies": [
                {
                    "company_name": "企业A",
                    "fleet": [{"vehicle_type": "重型柴油货车", "count": 20, "annual_km": 80000}],
                },
                {
                    "company_name": "企业B",
                    "fleet": [{"vehicle_type": "轻型柴油货车", "count": 30, "annual_km": 40000}],
                },
            ]
        }
        code, data, err = run_bridge("compare", payload)
        assert code == 0
        assert "ranking_by_emission" in data
        assert len(data["comparison"]) == 2

    def test_turnover_command(self):
        payload = {
            "fleet": [
                {
                    "vehicle_type": "重型柴油货车",
                    "count": 10,
                    "annual_km": 100000.0,
                    "load_factor": 0.80,
                },
                {
                    "vehicle_type": "新能源物流车",
                    "count": 5,
                    "annual_km": 30000.0,
                    "load_factor": 0.75,
                },
            ],
            "region": "广东",
            "green_electricity_ratio": 0.2,
        }
        code, data, err = run_bridge("turnover", payload)
        assert code == 0
        assert "scope2" in data
        assert "turnover_and_intensity" in data
        assert data["scope2"]["electric_vehicle_count"] == 5
        assert data["turnover_and_intensity"]["total_turnover_wan_tkm"] > 0

    def test_invalid_command(self):
        code, data, err = run_bridge("invalid_action")
        assert code != 0
