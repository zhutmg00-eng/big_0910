"""安全姿态自检：无鉴权运行必须可被程序与运维发现。

背景：APP_API_KEY 未设置时全部端点（含 POST /api/kb/ingest-all，会重建知识库）
都无需凭证即可调用。README 写了警告，但程序本身没有任何出口能自证状态——
运维只看到 200，看不出自己正在裸奔。

更隐蔽的一种：照抄 .env.example 得到 APP_API_KEY=your-api-key-here，
若判为「已配置」，服务就进入「看起来受保护、实际人人可过」的状态，
比不设更危险。本模块把这两种失效都锁死。
"""
from fastapi.testclient import TestClient

from src.api.main import app, build_security_posture


class TestPostureClassification:
    def test_unset_key_is_open_dev_mode(self):
        posture = build_security_posture("")
        assert posture["auth_required"] is False
        assert posture["mode"] == "open_dev"
        assert posture["warning"], "无鉴权运行必须给出可读警告"

    def test_warning_names_the_dangerous_endpoint(self):
        """警告必须点名会重建知识库的写接口，只说「不安全」等于没说。"""
        posture = build_security_posture("")
        assert "/api/kb/ingest-all" in posture["warning"]

    def test_placeholder_key_is_not_treated_as_protected(self):
        """照抄 .env.example 不构成保护——这是最容易被误判为安全的情况。"""
        for placeholder in ("your-api-key-here", "changeme", "dev-key", "  CHANGEME  "):
            posture = build_security_posture(placeholder)
            assert posture["auth_required"] is False, (
                f"占位值 {placeholder!r} 被判为已鉴权，鉴权形同虚设"
            )
            assert posture["mode"] == "placeholder_key"
            assert "占位符" in posture["warning"]

    def test_real_key_reports_protected_without_warning(self):
        posture = build_security_posture("a7f3k9x2-not-a-placeholder")
        assert posture["auth_required"] is True
        assert posture["mode"] == "protected"
        assert posture["warning"] == ""

    def test_modes_are_mutually_distinct(self):
        modes = {
            build_security_posture("")["mode"],
            build_security_posture("your-api-key-here")["mode"],
            build_security_posture("real-secret-value")["mode"],
        }
        assert len(modes) == 3


class TestHealthExposesPosture:
    def test_health_endpoint_reports_security_block(self):
        client = TestClient(app)
        resp = client.get("/api/health")
        assert resp.status_code == 200
        body = resp.json()
        assert "security" in body
        assert set(body["security"]) == {"auth_required", "mode", "warning"}
        # 三态自洽：不需要鉴权时必须有警告，需要时警告必须为空
        if body["security"]["auth_required"]:
            assert body["security"]["warning"] == ""
        else:
            assert body["security"]["warning"]

    def test_health_reports_open_or_placeholder_when_no_safe_key(self):
        """测试环境清空了 APP_API_KEY，因此这里必须报「未受保护」。"""
        body = TestClient(app).get("/api/health").json()
        assert body["security"]["auth_required"] is False
        assert body["security"]["mode"] in {"open_dev", "placeholder_key"}


class TestVerifyApiKeyConsistency:
    def test_placeholder_key_does_not_block_requests(self, monkeypatch):
        """第14轮盲审 P0-2：占位符模式下自检报 auth_required:false，中间件不得强制 401。"""
        import src.api.main as api_main
        monkeypatch.setattr(api_main, "API_KEY", "your-api-key-here")
        client = TestClient(app)
        payload = {
            "company_name": "测试物流企业",
            "fleet": [{"vehicle_type": "重型柴油货车", "count": 10, "annual_km": 80000, "load_factor": 0.75}],
        }
        # 未携带 X-API-Key Header，占位符模式下应正常放行
        resp = client.post("/api/calculate", json=payload)
        assert resp.status_code == 200, f"占位符模式下应免鉴权放行，实际返回 {resp.status_code}: {resp.text}"

    def test_real_key_blocks_unauthorized_requests(self, monkeypatch):
        """真实密钥受保护模式下，必须拦截未带正确 Header 的请求。"""
        import src.api.main as api_main
        monkeypatch.setattr(api_main, "API_KEY", "real-production-secret-999")
        client = TestClient(app)
        payload = {
            "company_name": "测试物流企业",
            "fleet": [{"vehicle_type": "重型柴油货车", "count": 10, "annual_km": 80000, "load_factor": 0.75}],
        }
        resp = client.post("/api/calculate", json=payload)
        assert resp.status_code == 401
        # 带正确 Header 则放行
        resp_authed = client.post("/api/calculate", json=payload, headers={"X-API-Key": "real-production-secret-999"})
        assert resp_authed.status_code == 200

