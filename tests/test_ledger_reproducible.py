"""派生指标台账必须能从仓库现有数据+引擎**复现**，不能是手抄的旧快照。

背景（真实缺陷，实测于 2026-10-31）：
`docs/derived_metrics.json` 是论文、图表与答辩材料里一切数字的唯一台账。
但仓库里没有任何测试校验它是否还能算出来——`test_claim_consistency.py`
只比对「文档写的数」与「台账里的数」，两边一起过期时全绿。

实测撞到的漂移：台账的 `rag.payload` 嵌了一份 RAG 评测结果副本，
当时记录的是 39 份 / 281 块快照（keyword MRR 0.4879），
而 `docs/rag_benchmark/rag_retrieval_experiment_results.json` 早已是
38 份 / 283 块（MRR 0.4628）。重跑 `scripts/gen_derived_metrics.py`
产生 545 行新增 / 410 行删除，全部集中在这一段。

本文件锁两件事：
1. 台账里嵌入的 RAG 载荷必须与结果文件逐字段一致（防止副本静默漂移）；
2. RQ1 的标定点误差必须能用引擎从 `benchmark_fleets.json` 复算出来
   （防止引擎参数改了、台账还留着旧读数）。

只校验可机器复现的量；`sensitivity` 的网格扫描代价较高，交由
`scripts/sensitivity_analysis.py` 自己的输出负责，本文件不重复跑。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LEDGER = ROOT / "docs" / "derived_metrics.json"
RAG_RESULTS = ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json"
FLEET_JSON = ROOT / "data" / "raw" / "real_fleets" / "benchmark_fleets.json"


def _ledger() -> dict:
    return json.loads(LEDGER.read_text(encoding="utf-8"))


class TestEmbeddedRagPayloadHasNotDrifted:
    def test_payload_equals_source_file(self) -> None:
        """台账的 rag.payload 必须是结果文件的逐字段副本。"""
        rag = _ledger().get("rag") or {}
        payload = rag.get("payload")
        assert payload, "台账缺少 rag.payload，图表与论文将失去 RAG 数字来源"
        current = json.loads(RAG_RESULTS.read_text(encoding="utf-8"))
        assert payload == current, (
            "台账里的 RAG 载荷与 docs/rag_benchmark/rag_retrieval_experiment_results.json "
            "不一致——说明评测重跑后没有执行 python scripts/gen_derived_metrics.py。"
            f"台账记录 {payload.get('benchmark_metadata', {}).get('total_documents')} 份 / "
            f"{payload.get('benchmark_metadata', {}).get('total_chunks')} 块；"
            f"当前结果 {current.get('benchmark_metadata', {}).get('total_documents')} 份 / "
            f"{current.get('benchmark_metadata', {}).get('total_chunks')} 块。"
        )

    def test_source_file_is_recorded_and_exists(self) -> None:
        rag = _ledger().get("rag") or {}
        src = rag.get("source_file")
        assert src, "台账未记录 RAG 数字的来源文件"
        assert (ROOT / src).is_file(), f"台账声明的来源文件不存在：{src}"


class TestRq1MapeRecomputesFromEngine:
    """RQ1 的标定点误差必须能从引擎 + 车队台账现算出来。"""

    @staticmethod
    def _recompute() -> list[float]:
        from src.engine.calculator import VehicleGroupData, calculate_emission
        from src.engine.emission_factors import get_all_factors  # noqa: F401  (确保表可加载)

        data = json.loads(FLEET_JSON.read_text(encoding="utf-8"))
        conv = data["metadata"]["emission_conversion_factors"]
        kg = {
            "柴油": conv["diesel_kg_co2_per_liter"],
            "汽油": conv["gasoline_kg_co2_per_liter"],
            "LNG": conv["lng_kg_co2_per_kg"],
        }
        errors = []
        for bench in data["benchmarks"]:
            groups = [
                VehicleGroupData(
                    vehicle_type=v["vehicle_type"],
                    count=v["count"],
                    annual_km=v["annual_km"],
                    load_factor=v["load_factor"],
                )
                for v in bench["fleet_input"]
            ]
            e_model = calculate_emission(groups).total_emission_t
            led = bench["real_energy_ledger"]
            e_fuel = (
                led["diesel_liters"] * kg["柴油"]
                + led["gasoline_liters"] * kg["汽油"]
                + led["lng_kg"] * kg["LNG"]
            ) / 1000.0
            errors.append((e_model - e_fuel) / e_fuel * 100)
        return errors

    def test_per_case_errors_match_ledger(self) -> None:
        ledger_cases = {c["id"]: c["rel_err_pct"] for c in _ledger()["fleet_cases"]}
        data = json.loads(FLEET_JSON.read_text(encoding="utf-8"))
        ids = [b["benchmark_id"] for b in data["benchmarks"]]
        recomputed = self._recompute()
        assert len(ids) == len(recomputed)
        for case_id, got in zip(ids, recomputed, strict=True):
            assert case_id in ledger_cases, f"台账缺少案例 {case_id}"
            assert ledger_cases[case_id] == pytest.approx(round(got, 2), abs=0.01), (
                f"{case_id} 台账记录相对误差 {ledger_cases[case_id]}%，"
                f"引擎现算 {got:.2f}%——引擎参数或车队台账已变，需重跑 gen_derived_metrics"
            )

    def test_equal_weight_mape_matches_ledger(self) -> None:
        """对外最常引用的 4.23% 必须等于四案例等权平均。"""
        errors = self._recompute()
        expected = sum(errors) / len(errors)
        recorded = _ledger()["mape"]["equal_weight_pct"]
        assert recorded == pytest.approx(round(expected, 2), abs=0.01), (
            f"台账等权 MAPE {recorded}%，现算 {expected:.2f}%"
        )

    def test_ledger_declares_its_generator(self) -> None:
        assert _ledger().get("generated_by") == "scripts/gen_derived_metrics.py"
