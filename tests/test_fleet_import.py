"""车队台账导入的解析规则与接口守卫。

来源：第 8/9 轮独立评审的核心结论——「最致命的短板不是算得不准，而是根本
没有把一家真实车队的账搬进去的入口」。这里锁住三件事：

1. 真实台账的脏数据（GBK 编码、分号分隔、``75`` 表示 75%、千分位、
   「重卡／轻卡」口语车型、按车牌一行）都能被正确解析；
2. 每一处纠正都出现在 ``warnings`` 里，不静默猜测；
3. 认不出的车型与非法数量被跳过而不是被硬塞进结果。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.engine.emission_factors import get_all_factors
from src.engine.fleet_import import (
    FleetImportError,
    parse_fleet_file,
    parse_fleet_table,
    resolve_vehicle_type,
)


def _csv(*rows: str) -> str:
    return "\n".join(rows) + "\n"


TEMPLATE_CSV = _csv(
    "车型,数量,年均里程(km),实载率",
    "重型柴油货车,40,110000,0.72",
    "轻型柴油货车,30,45000,0.60",
)


class TestVehicleTypeResolution:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            ("重型柴油货车", "重型柴油货车"),
            ("重卡", "重型柴油货车"),
            ("轻卡", "轻型柴油货车"),
            ("中卡", "中型柴油货车"),
            ("LNG重卡", "LNG重型货车"),
            ("lng重卡", "LNG重型货车"),
            ("电动重卡", "新能源物流车"),
            ("纯电重卡", "新能源物流车"),
            ("牵引车", "重型柴油半挂牵引车(>49t)"),
            ("重型柴油货车（>31t）", "重型柴油货车(>31t)"),
            ("重型柴油 6×4 货车", "重型柴油货车"),
        ],
    )
    def test_synonyms_and_variants(self, raw, expected):
        assert resolve_vehicle_type(raw) == expected

    def test_unknown_returns_none_instead_of_guessing(self):
        assert resolve_vehicle_type("神秘新物种车") is None
        assert resolve_vehicle_type("") is None

    def test_every_canonical_name_resolves_to_itself(self):
        for name in get_all_factors():
            assert resolve_vehicle_type(name) == name


class TestDirtyRealWorldFiles:
    def test_semicolon_and_percent_style(self):
        # Excel 中文环境常见：分号分隔 + 实载率写 60
        content = _csv("车型;数量;年行驶里程;里程利用率", "重卡;40;110000;60", "轻卡;30;45000;75")
        result = parse_fleet_table(content)
        assert result.total_vehicles == 70
        assert {g.vehicle_type for g in result.groups} == {"重型柴油货车", "轻型柴油货车"}
        lf = {g.vehicle_type: g.load_factor for g in result.groups}
        assert lf["重型柴油货车"] == pytest.approx(0.60)
        assert lf["轻型柴油货车"] == pytest.approx(0.75)
        assert any(w.field_name == "load_factor" for w in result.warnings)

    def test_thousands_separator_and_units(self):
        content = _csv("车型,数量,年均里程", "重型柴油货车,\"1,200\",\"110,000 km/年\"")
        result = parse_fleet_table(content)
        assert result.groups[0].count == 1200
        assert result.groups[0].annual_km == pytest.approx(110000)

    def test_gbk_encoded_bytes(self):
        raw = TEMPLATE_CSV.encode("gbk")
        result = parse_fleet_file("台账.csv", raw)
        assert result.total_vehicles == 70

    def test_utf8_bom_exported_from_excel(self):
        raw = ("\ufeff" + TEMPLATE_CSV).encode("utf-8")
        result = parse_fleet_file("台账.csv", raw)
        assert result.total_vehicles == 70

    def test_tab_delimited(self):
        content = _csv("车型\t数量\t年均里程", "重型柴油货车\t40\t110000")
        assert parse_fleet_table(content).total_vehicles == 40

    def test_per_plate_rows_are_merged_by_weight(self):
        # 按车牌一行：同车型多行，里程不同，必须按车辆数加权而不是取平均
        content = _csv(
            "车型,数量,年均里程,实载率",
            "重卡,1,200000,0.9",
            "重卡,9,80000,0.5",
        )
        result = parse_fleet_table(content)
        assert len(result.groups) == 1
        group = result.groups[0]
        assert group.count == 10
        assert group.rows == 2
        assert group.annual_km == pytest.approx((200000 + 9 * 80000) / 10)
        assert group.load_factor == pytest.approx((0.9 + 9 * 0.5) / 10, abs=1e-4)
        assert any("加权合并" in note for note in result.notes)

    def test_trailing_blank_rows_ignored(self):
        content = _csv("车型,数量,年均里程", "重型柴油货车,40,110000", "", ",,")
        result = parse_fleet_table(content)
        assert result.rows_read == 1
        assert not result.warnings


class TestRefusesToGuess:
    def test_unknown_vehicle_type_skipped_with_warning(self):
        content = _csv("车型,数量,年均里程", "重型柴油货车,40,110000", "外星货车,10,100000")
        result = parse_fleet_table(content)
        assert result.total_vehicles == 40
        assert len(result.warnings) == 1
        assert "外星货车" in result.warnings[0].message

    def test_non_positive_count_skipped(self):
        content = _csv("车型,数量,年均里程", "重型柴油货车,0,110000", "轻型柴油货车,-5,45000", "重型柴油货车,7,90000")
        result = parse_fleet_table(content)
        assert result.total_vehicles == 7
        assert len(result.warnings) == 2

    def test_kilometre_above_physical_limit_is_capped_and_flagged(self):
        content = _csv("车型,数量,年均里程", "重型柴油货车,40,1000000000")
        result = parse_fleet_table(content)
        assert result.groups[0].annual_km == pytest.approx(300000)
        assert any("上限" in w.message for w in result.warnings)

    def test_missing_km_column_uses_default_and_says_so(self):
        content = _csv("车型,数量", "重型柴油货车,40")
        result = parse_fleet_table(content, default_annual_km=80000)
        assert result.groups[0].annual_km == pytest.approx(80000)
        assert any("未找到里程列" in note for note in result.notes)

    def test_missing_required_column_raises(self):
        with pytest.raises(FleetImportError) as exc:
            parse_fleet_table(_csv("车型,年均里程", "重型柴油货车,110000"))
        assert "数量" in str(exc.value)

    def test_header_only_raises(self):
        with pytest.raises(FleetImportError):
            parse_fleet_table(_csv("车型,数量,年均里程"))

    def test_all_rows_invalid_raises_instead_of_empty_success(self):
        with pytest.raises(FleetImportError):
            parse_fleet_table(_csv("车型,数量,年均里程", "甲,1,1", "乙,2,2"))

    def test_excel_is_rejected_with_actionable_message(self):
        with pytest.raises(FleetImportError) as exc:
            parse_fleet_file("台账.xlsx", b"PK\x03\x04")
        assert "另存为" in str(exc.value)
        assert "CSV" in str(exc.value)

    def test_oversized_file_rejected(self):
        with pytest.raises(FleetImportError) as exc:
            parse_fleet_file("big.csv", b"a" * (3 * 1024 * 1024))
        assert "上限" in str(exc.value)


class TestImportApi:
    @pytest.fixture()
    def client(self, monkeypatch):
        import src.api.main as api_main

        monkeypatch.setattr(api_main, "API_KEY", "")
        return TestClient(api_main.app)

    def test_template_is_downloadable_csv_with_bom(self, client):
        response = client.get("/api/fleet/template")
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        assert "attachment" in response.headers["content-disposition"]
        text = response.content.decode("utf-8-sig")
        assert text.splitlines()[0] == "车型,数量,年均里程(km),实载率"
        # 模板里的车型必须全部能被解析回来，否则模板自己就是错的
        for line in text.splitlines()[1:5]:
            assert parse_fleet_table("车型,数量,年均里程,实载率\n" + line) is not None

    def test_import_returns_normalised_groups(self, client):
        response = client.post(
            "/api/fleet/import",
            files={"file": ("台账.csv", TEMPLATE_CSV.encode("utf-8"), "text/csv")},
        )
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["total_vehicles"] == 70
        assert payload["rows_read"] == 2
        assert payload["filename"] == "台账.csv"
        assert payload["detected_columns"]["vehicle_type"] == "车型"
        # 解析结果必须能直接回填到 /api/calculate 的 VehicleInput
        from src.models.fleet import VehicleInput

        for group in payload["groups"]:
            VehicleInput(
                vehicle_type=group["vehicle_type"],
                count=group["count"],
                annual_km=group["annual_km"],
                load_factor=group["load_factor"],
            )

    def test_bad_file_returns_400_not_500(self, client):
        response = client.post(
            "/api/fleet/import",
            files={"file": ("坏.csv", b"foo,bar\n1,2\n", "text/csv")},
        )
        assert response.status_code == 400
        assert "缺少必需列" in response.json()["detail"]

    def test_import_requires_auth_when_key_configured(self, monkeypatch):
        import src.api.main as api_main

        monkeypatch.setattr(api_main, "API_KEY", "secret-key")
        anonymous = TestClient(api_main.app)
        response = anonymous.post(
            "/api/fleet/import",
            files={"file": ("台账.csv", TEMPLATE_CSV.encode("utf-8"), "text/csv")},
        )
        assert response.status_code == 401
        ok = anonymous.post(
            "/api/fleet/import",
            files={"file": ("台账.csv", TEMPLATE_CSV.encode("utf-8"), "text/csv")},
            headers={"X-API-Key": "secret-key"},
        )
        assert ok.status_code == 200

    def test_imported_groups_can_be_calculated(self, client):
        """端到端：上传 → 拿分组 → 直接算排放，验证没有口径断层。"""
        imported = client.post(
            "/api/fleet/import",
            files={"file": ("台账.csv", TEMPLATE_CSV.encode("utf-8"), "text/csv")},
        ).json()
        response = client.post(
            "/api/calculate",
            json={
                "company_name": "导入测试物流",
                "fleet": [
                    {
                        "vehicle_type": g["vehicle_type"],
                        "count": g["count"],
                        "annual_km": g["annual_km"],
                        "load_factor": g["load_factor"],
                    }
                    for g in imported["groups"]
                ],
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["total_vehicles"] == 70
        assert response.json()["total_emission_t"] > 0


class TestUiUploadPath:
    """UI「上传台账」按钮那条路必须真把结果落进 session_state。

    打桩 requests 而不是连真服务：本机 8000 端口常被别的进程占用（第 9 轮
    评审实测就是被 node 服务占着），真实 HTTP 会拿到陌生服务的 404，那是
    另一个缺陷，不该让本测试随机失败。
    """

    _SCRIPT = """
import streamlit as st
import src.ui.views.overview as ov

PAYLOAD = {
    "groups": [
        {"vehicle_type": "重型柴油货车", "count": 40, "annual_km": 110000.0, "load_factor": 0.72},
        {"vehicle_type": "轻型柴油货车", "count": 30, "annual_km": 45000.0, "load_factor": 0.6},
    ],
    "warnings": [{"row": 2, "field": "实载率", "message": "72 按 72% 理解"}],
    "notes": ["台账没有年均里程列，已用默认 80000 km"],
    "total_vehicles": 70,
    "rows_read": 2,
    "detected_columns": {"车型": "vehicle_type", "数量": "count"},
    "filename": "台账.csv",
}

class FakeResponse:
    status_code = 200
    text = ""

    def json(self):
        return PAYLOAD

class FakeUpload:
    name = "台账.csv"

    def getvalue(self):
        return b"x"

ov.requests.post = lambda *a, **k: FakeResponse()
ov._import_fleet_csv(FakeUpload())
st.write(st.session_state["fleet_data"])
"""

    def _run(self):
        from streamlit.testing.v1 import AppTest

        at = AppTest.from_string(self._SCRIPT, default_timeout=120).run()
        assert not at.exception, at.exception[0].value if at.exception else ""
        return at

    def test_upload_replaces_fleet_and_keeps_notes(self):
        at = self._run()
        fleet = at.session_state["fleet_data"]
        assert len(fleet) == 2
        assert sum(item["count"] for item in fleet) == 70
        assert fleet[0]["annual_km"] == 110000
        assert abs(fleet[0]["load_factor"] - 0.72) < 1e-9
        assert at.session_state["fleet_import_notes"]
        assert at.session_state["fleet_import_warnings"]
        assert at.session_state["fleet_import_summary"]["total_vehicles"] == 70
