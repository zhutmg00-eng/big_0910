"""API接口测试"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


class TestAPI:
    def test_health_check(self):
        """健康检查"""
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_vehicle_types(self):
        """车型列表"""
        response = client.get("/api/vehicle-types")
        assert response.status_code == 200
        data = response.json()
        assert "vehicle_types" in data
        assert len(data["vehicle_types"]) >= 6

    def test_calculate_heavy_trucks(self):
        """计算重型货车碳排放"""
        response = client.post("/api/calculate", json={
            "company_name": "测试物流公司",
            "fleet": [{
                "vehicle_type": "重型柴油货车",
                "count": 50,
                "annual_km": 80000,
                "load_factor": 0.75,
            }]
        })
        assert response.status_code == 200
        result = response.json()
        assert result["company_name"] == "测试物流公司"
        assert result["total_emission_t"] > 3000
        assert result["total_vehicles"] == 50
        assert result["carbon_budget"]["状态"] in {"超出预算", "低于预算", "基本平衡"}
        assert result["carbon_budget"]["模拟碳预算_t"] == 3157.2
        assert result["carbon_budget"]["预算差额_t"] == 350.8
        assert result["carbon_budget"]["情景减排目标"] == 0.10
        assert "购电间接排放" in result["methodology_note"]

    def test_calculate_accepts_custom_budget_target(self):
        response = client.post("/api/calculate", json={
            "company_name": "零目标情景",
            "scenario_reduction_target": 0,
            "fleet": [{
                "vehicle_type": "重型柴油货车",
                "count": 50,
                "annual_km": 80000,
                "load_factor": 0.75,
            }],
        })
        assert response.status_code == 200
        budget = response.json()["carbon_budget"]
        assert budget["模拟碳预算_t"] == 3508.0
        assert budget["状态"] == "基本平衡"

    @pytest.mark.parametrize("target", [-0.1, 1.0])
    def test_calculate_rejects_invalid_budget_target(self, target):
        response = client.post("/api/calculate", json={
            "company_name": "目标边界测试",
            "scenario_reduction_target": target,
            "fleet": [{
                "vehicle_type": "重型柴油货车",
                "count": 1,
                "annual_km": 80000,
                "load_factor": 0.75,
            }],
        })
        assert response.status_code == 422

    def test_calculate_empty_fleet(self):
        """空车队应在进入计算引擎前被拒绝"""
        response = client.post("/api/calculate", json={
            "company_name": "空公司",
            "fleet": []
        })
        assert response.status_code == 422

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("count", -1),
            ("annual_km", -100),
            ("load_factor", 1.2),
            ("load_factor", -0.1),
        ],
    )
    def test_calculate_rejects_invalid_vehicle_values(self, field, value):
        vehicle = {
            "vehicle_type": "重型柴油货车",
            "count": 1,
            "annual_km": 10000,
            "load_factor": 0.75,
        }
        vehicle[field] = value
        response = client.post(
            "/api/calculate",
            json={"company_name": "边界测试", "fleet": [vehicle]},
        )
        assert response.status_code == 422

    def test_calculate_rejects_unknown_vehicle_type(self):
        response = client.post("/api/calculate", json={
            "company_name": "未知车型测试",
            "fleet": [{
                "vehicle_type": "不存在的车型",
                "count": 1,
                "annual_km": 10000,
                "load_factor": 0.75,
            }],
        })
        assert response.status_code == 422

    def test_calculate_rejects_blank_company_name(self):
        response = client.post("/api/calculate", json={
            "company_name": "   ",
            "fleet": [{
                "vehicle_type": "重型柴油货车",
                "count": 1,
                "annual_km": 10000,
                "load_factor": 0.75,
            }],
        })
        assert response.status_code == 422

    def test_calculate_mixed_fleet(self):
        """混合车队"""
        response = client.post("/api/calculate", json={
            "company_name": "混合车队公司",
            "fleet": [
                {"vehicle_type": "重型柴油货车", "count": 20, "annual_km": 80000, "load_factor": 0.75},
                {"vehicle_type": "中型柴油货车", "count": 30, "annual_km": 50000, "load_factor": 0.75},
                {"vehicle_type": "新能源物流车", "count": 10, "annual_km": 40000, "load_factor": 0.75},
            ]
        })
        assert response.status_code == 200
        result = response.json()
        assert result["total_vehicles"] == 60
        # 新能源车排放为0，不影响总量
        assert result["total_emission_t"] > 0

    @pytest.mark.parametrize("question", ["   ", "问题" * 251])
    def test_ask_rejects_invalid_question(self, question):
        response = client.post(
            "/api/ask",
            json={"question": question, "carbon_profile": {}},
        )
        assert response.status_code == 422

    def test_kb_health_endpoint_reports_structured_selfcheck(self):
        """知识库健康自检必须给出结构化结论，而不是一个布尔值。

        背景：collection 名由嵌入模型哈希派生，换模型会静默新建空 collection，
        旧语料留在磁盘但不再被读到，政策问答从此返回空结果且无任何报错。
        这个接口是把该故障暴露出来的唯一入口。
        """
        response = client.get("/api/kb/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] in {"ok", "empty", "degraded"}
        for key in ("count", "documents", "embedding_model", "collection_name",
                    "other_collections", "warning"):
            assert key in data, f"自检结果缺少字段 {key}"
        assert isinstance(data["other_collections"], dict)
        # status 与 count 必须自洽，否则调用方无法据此判断
        if data["status"] == "empty":
            assert data["count"] == 0
            assert data["warning"], "空库必须给出可执行的修复指引"
        if data["status"] == "ok":
            assert data["count"] > 0
            assert data["warning"] == ""


class TestNonFinitePayloadHandling:
    """JSON 里写 NaN / Infinity 是合法的（json.loads 接受），必须稳定返回 422。

    第 9 轮评审实测：校验失败时 Pydantic 把 ``float('nan')`` 放进 ``input``，
    默认 JSONResponse 用 ``allow_nan=False`` 序列化失败 → ``500 text/plain
    'Internal Server Error'``，且响应没有 ``X-Request-ID``，日志中查不到。
    """

    _NAN_BODY = (
        '{"company_name":"x","fleet":[{"vehicle_type":"重型柴油货车",'
        '"count":50,"annual_km":NaN,"load_factor":0.7}]}'
    )
    _INF_BODY = (
        '{"company_name":"x","fleet":[{"vehicle_type":"重型柴油货车",'
        '"count":Infinity,"annual_km":100000,"load_factor":0.7}]}'
    )

    def test_nan_payload_returns_422_not_500(self):
        response = client.post(
            "/api/calculate", content=self._NAN_BODY, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422, response.text
        assert response.headers.get("content-type", "").startswith("application/json")

    def test_infinity_payload_returns_422_not_500(self):
        response = client.post(
            "/api/calculate", content=self._INF_BODY, headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 422, response.text

    @pytest.mark.parametrize("body", ["_NAN_BODY", "_INF_BODY"])
    def test_validation_error_keeps_request_id(self, body):
        """任何 422 都必须带 X-Request-ID，否则用户报错时无从定位。"""
        import src.api.main as api_main

        saved = api_main.API_KEY
        api_main.API_KEY = ""
        try:
            client = TestClient(api_main.app, raise_server_exceptions=False)
            response = client.post(
                "/api/calculate",
                content=getattr(self, body),
                headers={"Content-Type": "application/json"},
            )
        finally:
            api_main.API_KEY = saved
        assert response.status_code == 422
        assert response.headers.get("X-Request-ID")


class TestAbsurdInputsAreRejected:
    """第 8 轮评审：count=10**6、annual_km=1e12 直接 200，没人拦。

    上界不是安全边界，是笔误边界——把「吨」填进「辆」、把「月里程」
    乘 12 再加两个零，用户自己不一定会发现，但结果会荒谬一个量级。
    """

    def _post(self, **overrides):
        group = {"vehicle_type": "重型柴油货车", "count": 50, "annual_km": 100000, "load_factor": 0.7}
        group.update(overrides)
        return client.post("/api/calculate", json={"company_name": "越界测试", "fleet": [group]})

    def test_huge_count_rejected(self):
        response = self._post(count=10 ** 6)
        assert response.status_code == 422, response.text
        assert "车辆数量" in response.text or "count" in response.text

    def test_huge_annual_km_rejected(self):
        response = self._post(annual_km=1e12)
        assert response.status_code == 422, response.text

    def test_reasonable_values_still_pass(self):
        response = self._post(count=27_500, annual_km=180_000)
        assert response.status_code == 200, response.text

    def test_tco_rejects_huge_annual_km(self):
        response = client.post(
            "/api/tco/calculate",
            json={
                "vehicle_type": "重型柴油货车",
                "replace_count": 10,
                "annual_km": 1e12,
                "annual_co2_reduction_t": 0.0,
            },
        )
        assert response.status_code == 422, response.text


class TestPathSecurityAndKBIngest:
    """I-16：路径安全解析与知识库入库接口测试。

    I-17：这些端点会**真的写库**，必须隔离到临时目录。
    实测（2026-10-31）：只跑 `test_api_kb_ingest_relative_filename_200`,
    `data/chroma_db/chroma.sqlite3` 的 mtime 立刻变化——测试在改生产知识库。
    端点内部是函数级 import，所以 patch `src.config.POLICY_DOCS_DIR` 与
    `src.rag.PolicyAdvisor` / `src.rag.ingest_directory` 即可把它们引到临时库。
    """

    @pytest.fixture(autouse=True)
    def _isolate_kb(self, tmp_path, monkeypatch):
        from src.rag import PolicyAdvisor, ingest_directory
        from src.rag.vector_store import PolicyVectorStore

        docs = tmp_path / "policy_docs"
        docs.mkdir()
        (docs / "测试政策.md").write_text(
            "# 测试政策\n\n**发布时间**: 2024年5月6日\n\n第一条 本文件仅用于测试入库。\n",
            encoding="utf-8",
        )
        store = PolicyVectorStore(
            persist_dir=str(tmp_path / "kb"), embedding_model="chromadb-default"
        )
        self._temp_store = store
        self._temp_docs = docs

        monkeypatch.setattr("src.config.POLICY_DOCS_DIR", docs)
        monkeypatch.setattr(
            "src.rag.PolicyAdvisor",
            lambda *a, **k: PolicyAdvisor(vector_store=store),
        )
        monkeypatch.setattr(
            "src.rag.ingest_directory",
            lambda directory, vector_store=None, force=False: ingest_directory(
                directory, store, force=force
            ),
        )

    def test_fixture_actually_isolates_production_kb(self):
        """保险丝：跑完入库接口后，生产库的块数不能变。"""
        from src.config import CHROMA_DB_DIR
        from src.rag.vector_store import PolicyVectorStore

        production = PolicyVectorStore(persist_dir=str(CHROMA_DB_DIR))
        before = production.count()

        assert client.post(
            "/api/kb/ingest", params={"file_path": "测试政策.md"}
        ).status_code == 200

        after = PolicyVectorStore(persist_dir=str(CHROMA_DB_DIR)).count()
        assert after == before, (
            f"入库接口写到了生产知识库（{before} → {after}），测试隔离失效"
        )
        assert self._temp_store.count() > 0, "临时库应收到分块"

    def test_safe_resolve_pure_filename_success(self):
        from src.api.main import safe_resolve_path

        resolved = safe_resolve_path("测试政策.md", self._temp_docs)
        assert resolved.name == "测试政策.md"
        assert resolved.is_file()

    def test_safe_resolve_traversal_attack_raises_403(self):
        from fastapi import HTTPException
        from src.api.main import safe_resolve_path

        with pytest.raises(HTTPException) as exc_info:
            safe_resolve_path("../../.env", self._temp_docs)
        assert exc_info.value.status_code == 403

    def test_api_kb_ingest_relative_filename_200(self):
        response = client.post(
            "/api/kb/ingest",
            params={"file_path": "测试政策.md"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["file"] == "测试政策.md"
        assert data["chunks_added"] > 0

    def test_api_kb_ingest_traversal_rejected_403(self):
        response = client.post(
            "/api/kb/ingest",
            params={"file_path": "../../../.env"},
        )
        assert response.status_code == 403, response.text

    def test_api_kb_ingest_nonexistent_file_404(self):
        response = client.post(
            "/api/kb/ingest",
            params={"file_path": "nonexistent_doc_xyz123.md"},
        )
        assert response.status_code == 404, response.text

    def test_api_kb_ingest_all_returns_summary(self):
        response = client.post("/api/kb/ingest-all", params={"force": False})
        assert response.status_code == 200, response.text
        data = response.json()
        for key in ("documents", "chunks", "skipped"):
            assert key in data, f"缺少汇总字段 {key}"


class TestUncertaintyEndpoint:
    """I-16：POST /api/uncertainty 接口自动化测试。"""

    def test_uncertainty_valid_payload_returns_200_and_intervals(self):
        payload = {
            "fleet": [
                {"vehicle_type": "重型柴油货车", "count": 10, "annual_km": 80000, "load_factor": 0.75},
                {"vehicle_type": "中型柴油货车", "count": 20, "annual_km": 50000, "load_factor": 0.75},
            ],
            "n_samples": 500,
            "mileage_cv": 0.10,
            "load_factor_halfwidth": 0.05,
        }
        response = client.post("/api/uncertainty", json=payload)
        assert response.status_code == 200, response.text
        data = response.json()
        for key in ("point_estimate_t", "p5_t", "p50_t", "p95_t", "histogram", "variance_contributions"):
            assert key in data, f"结果缺少 {key}"
        # 物理区间严格单调
        assert data["p5_t"] <= data["p50_t"] <= data["p95_t"]
        assert data["point_estimate_t"] > 0
        assert isinstance(data["variance_contributions"], dict)

    def test_uncertainty_empty_fleet_rejected_422(self):
        response = client.post(
            "/api/uncertainty",
            json={"fleet": [], "n_samples": 500},
        )
        assert response.status_code == 422, response.text

    def test_uncertainty_unknown_vehicle_type_rejected_422(self):
        response = client.post(
            "/api/uncertainty",
            json={
                "fleet": [{"vehicle_type": "虚构火星飞船", "count": 5, "annual_km": 10000}],
            },
        )
        assert response.status_code == 422, response.text

