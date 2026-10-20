"""v0.4 新增能力的单元测试：BM25 / RRF / 不确定性分析 / 计算精度修复 / 新 API。"""
import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.engine.calculator import VehicleGroupData as V, calculate_emission
from src.engine.uncertainty import ef_range, monte_carlo_emission
from src.rag.bm25 import BM25Index, reciprocal_rank_fusion, tokenize
from src.rag.vector_store import PolicyVectorStore

client = TestClient(app)


# ---------------------------------------------------------------- BM25 / RRF
def test_tokenize_keeps_domain_terms_and_drops_stopwords():
    toks = tokenize("物流企业是否需要履行全国碳市场的配额清缴义务？")
    assert "全国碳市场" in toks or "碳市场" in toks
    assert "配额清缴" in toks or "清缴" in toks
    assert "是否" not in toks and "的" not in toks


def test_bm25_ranks_relevant_document_first():
    idx = BM25Index(
        ["a", "b", "c"],
        ["发电行业重点排放单位配额分配方案", "交通运输碳达峰实施方案 推广新能源货车", "钢铁行业温室气体核算指南"],
    )
    assert idx.top_k("新能源货车 交通运输", 1)[0][0] == 1
    assert idx.top_k("完全无关的查询词汇xyz", 3) == []


def test_rrf_is_rank_based_and_rewards_agreement():
    fused = reciprocal_rank_fusion([["x", "y", "z"], ["y", "x", "w"]], k=60)
    names = [d for d, _ in fused]
    assert set(names[:2]) == {"x", "y"}
    assert names[-1] in {"z", "w"}
    # 两路都排第一的文档得分 = 2/61
    only = reciprocal_rank_fusion([["d"], ["d"]], k=60)
    assert only[0][1] == pytest.approx(2 / 61)


def test_vector_store_bm25_mode_without_embeddings(tmp_path):
    vs = PolicyVectorStore(persist_dir=str(tmp_path / "db"), embedding_model="chromadb-default")
    # 直接写入（跳过嵌入计算），只验证 BM25 路径
    vs.collection.add(
        ids=["p_0", "p_1"],
        documents=["来源文档：p\n交通运输行业推广新能源物流车", "来源文档：p\n发电行业配额清缴"],
        metadatas=[{"source": "p"}, {"source": "p"}],
        embeddings=[[0.1] * 8, [0.2] * 8],
    )
    res = vs.search("新能源物流车", k=1, mode="bm25")
    assert res[0]["id"] == "p_0" and res[0]["retrievers"] == ["bm25"]
    with pytest.raises(ValueError):
        vs.search("x", mode="not-a-mode")


# ---------------------------------------------------------------- 计算精度修复
def test_same_vehicle_type_multiple_groups_weighted_load_adjustment():
    res = calculate_emission([V("重型柴油货车", 10, 80000, 0.55), V("重型柴油货车", 10, 80000, 0.95)])
    row = res.emission_by_type["重型柴油货车"]
    assert row["车辆数"] == 20
    # 0.55 → 1.03；0.95 → 1.0；等车公里加权 = 1.015（旧版会被后一组覆盖成 1.0）
    assert row["满载率调整系数"] == pytest.approx(1.015, abs=1e-4)
    assert row["排放量_tCO2"] == pytest.approx(res.total_emission_t, abs=0.01)


# ---------------------------------------------------------------- 不确定性
def test_ef_range_uses_multi_source_values():
    lng = ef_range("LNG重型货车")
    assert lng["low"] <= 0.72 * 0.9 + 1e-9 and lng["high"] == pytest.approx(1.2)
    assert ef_range("新能源物流车")["dist"] == "fixed"


def test_monte_carlo_is_reproducible_and_brackets_point_estimate():
    fleet = [V("重型柴油货车", 50, 80000, 0.6), V("轻型柴油货车", 30, 30000, 0.75)]
    a = monte_carlo_emission(fleet, n_samples=5000, seed=7)
    b = monte_carlo_emission(fleet, n_samples=5000, seed=7)
    assert a.p50_t == b.p50_t
    assert a.p5_t < a.point_estimate_t < a.p95_t
    assert 0 < a.relative_uncertainty_pct < 50
    assert abs(sum(a.contributions.values()) - 1) < 0.02
    assert sum(a.histogram["counts"]) == 5000


def test_better_data_quality_narrows_interval():
    fleet = [V("重型柴油货车", 50, 80000, 0.75)]
    ledger = monte_carlo_emission(fleet, n_samples=5000, data_quality="台账")
    guess = monte_carlo_emission(fleet, n_samples=5000, data_quality="估计")
    assert ledger.relative_uncertainty_pct < guess.relative_uncertainty_pct


def test_zero_emission_fleet_has_zero_uncertainty():
    r = monte_carlo_emission([V("新能源物流车", 10, 40000, 0.7)], n_samples=500)
    assert r.p95_t == 0 and r.relative_uncertainty_pct == 0


# ---------------------------------------------------------------- API
def test_uncertainty_endpoint():
    resp = client.post("/api/uncertainty", json={
        "fleet": [{"vehicle_type": "重型柴油货车", "count": 20, "annual_km": 80000, "load_factor": 0.7}],
        "n_samples": 2000, "data_quality": "台账",
    })
    assert resp.status_code == 200
    body = resp.json()
    assert body["p5_t"] < body["p50_t"] < body["p95_t"]
    assert "X-Request-ID" in resp.headers


def test_uncertainty_endpoint_validates_input():
    bad = client.post("/api/uncertainty", json={"fleet": [], "n_samples": 10})
    assert bad.status_code == 422
    bad_quality = client.post("/api/uncertainty", json={
        "fleet": [{"vehicle_type": "重型柴油货车", "count": 1, "annual_km": 1000}], "data_quality": "瞎猜"})
    assert bad_quality.status_code == 422


def test_health_reports_new_version():
    assert client.get("/api/health").json()["version"] == "0.4.0"
