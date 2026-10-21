"""用户侧错误信息与文件名的健壮性守卫。

来源：第八轮独立评审（产品/用户视角）实测到两处会把内部结构抛给终端用户：

1. 企业名超 100 字时，``show_api_error`` 会把 FastAPI 的 422 ``detail``
   原样打印成一大块 ``list[dict]``（含 ``input`` 里的全部用户输入与
   ``ctx`` 内部结构）。
2. 企业名含 ``| ? * < >`` 时 ``generate_carbon_report`` 直接抛
   ``OSError [Errno 22] Invalid argument``（原实现只替换了 ``/``）。

这些不是计算问题，但会让老板第一眼就放弃，所以单独立守卫。
"""

import io

import os
import subprocess
import sys
from pathlib import Path

import pytest
import requests

from src.ui.api_client import _humanize_detail
from src.ui.components.report import _safe_filename


class _FakeResponse:
    def __init__(self, status_code: int, payload, text: str = ""):
        self.status_code = status_code
        self._payload = payload
        self.text = text

    def json(self):
        if self._payload is None:
            raise ValueError("not json")
        return self._payload


_VALIDATION_DETAIL = [
    {
        "type": "string_too_long",
        "loc": ["body", "company_name"],
        "msg": "String should have at most 100 characters",
        "input": "超长物流集团" * 34,
        "ctx": {"max_length": 100},
    }
]


class TestValidationErrorIsHumanized:
    def test_does_not_leak_python_dict(self):
        text = _humanize_detail(_VALIDATION_DETAIL)
        assert "超长物流集团" not in text, "不得回显用户原始输入"
        assert "ctx" not in text and "string_too_long" not in text
        assert "{" not in text and "[" not in text

    def test_maps_field_name_and_limit(self):
        text = _humanize_detail(_VALIDATION_DETAIL)
        assert "企业名称" in text
        assert "100" in text

    def test_multiple_errors_are_joined(self):
        payload = [
            {"type": "missing", "loc": ["body", "fleet"], "msg": "Field required"},
            {
                "type": "less_than_equal",
                "loc": ["body", "fleet", 0, "annual_km"],
                "msg": "Input should be less than or equal to 300000",
                "input": 10 ** 9,
                "ctx": {"le": 300000},
            },
        ]
        text = _humanize_detail(payload)
        assert "车队清单" in text
        assert "年均里程" in text
        assert "300000" in text

    def test_plain_string_detail_passes_through(self):
        assert _humanize_detail("Invalid or missing API key") == "Invalid or missing API key"

    def test_empty_list_has_fallback_message(self):
        assert _humanize_detail([]) == "提交的内容未通过校验，请检查后重试"

    def test_show_api_error_renders_human_text(self, monkeypatch):
        import src.ui.api_client as api_client

        captured = {}
        monkeypatch.setattr(api_client.st, "error", lambda msg: captured.setdefault("msg", msg))
        resp = _FakeResponse(422, {"detail": _VALIDATION_DETAIL})
        api_client.show_api_error(resp)  # type: ignore[arg-type]
        msg = captured["msg"]
        assert "422" in msg
        assert "企业名称" in msg
        assert "超长物流集团" not in msg


class TestReportFilenameIsSanitized:
    @pytest.mark.parametrize(
        "raw",
        [
            "A|B?C*D<E>F",
            'a\\b/c:d*e?f"g<h>i|j',
            "顺丰速运集团华南区:冷链",
            "带\n换行\r和\t制表符",
        ],
    )
    def test_no_illegal_chars_survive(self, raw):
        cleaned = _safe_filename(raw)
        for ch in '\\/:*?"<>|\r\n\t':
            assert ch not in cleaned, f"{ch!r} 残留在文件名 {cleaned!r}"

    def test_special_name_is_still_usable(self, tmp_path):
        name = _safe_filename("A|B?C*D<E>F")
        target = tmp_path / f"{name}_报告_20261021.pdf"
        target.write_bytes(b"%PDF-1.4\n")
        assert target.exists()

    def test_empty_and_blank_names_fall_back(self):
        assert _safe_filename("") == "企业"
        assert _safe_filename("   ") == "企业"
        assert _safe_filename("...") == "企业"

    def test_length_is_capped(self):
        assert len(_safe_filename("物流" * 80)) == 60

    def test_chinese_name_preserved(self):
        assert _safe_filename("顺丰速运") == "顺丰速运"


def test_fake_response_helper_is_compatible_with_requests_shape():
    """确认 _FakeResponse 与真实 requests.Response 的接口一致。"""
    assert hasattr(requests.Response(), "json")
    assert _FakeResponse(422, {"detail": []}).status_code == 422


class TestBackendMissingDiagnosis:
    """端口被占用 / 后端没起来时，必须说人话，不能把陌生服务的路由名怼给用户。

    第 9 轮评审实测：本机 8000 端口被 node 服务占着，Streamlit 收到
    ``{"message": "Route POST:/api/calculate not found"}`` 并原样渲染，
    用户看到的是 ``Route POST:/api/calculate not found``。
    """

    def test_404_on_write_endpoint_is_diagnosed_as_wrong_service(self):
        from src.ui.api_client import _backend_missing_hint

        hint = _backend_missing_hint(404)
        assert "ApiWorker" not in hint
        assert "端口" in hint
        assert "API_BASE_URL" in hint

    def test_connection_error_is_translated_to_startup_hint(self):
        from src.ui.api_client import _describe_backend_down

        exc = requests.ConnectionError("HTTPConnectionPool(host='localhost', port=8000): Max retries exceeded")
        text = _describe_backend_down(exc)
        assert "连不上核算服务" in text
        assert "uvicorn" in text
        assert "端口" in text
        # 不把底层类名当唯一线索：应给出可执行动作
        assert "python -m uvicorn" in text


class TestUiNeverLeaksServerPaths:
    def test_advisory_uses_filename_not_absolute_path(self):
        import io as _io
        import pathlib
        import re

        source = _io.open(
            pathlib.Path(__file__).resolve().parent.parent / "src" / "ui" / "views" / "advisory.py",
            encoding="utf-8",
        ).read()
        assert not re.search(r'保存位置：\{report_path\}', source)

def test_factor_table_converts_to_arrow():
    """排放因子表混入字符串会让 st.dataframe 抛 ArrowInvalid（页面一打开就崩）。

    16 种车型里有 12 种没有百公里油耗参考值，数值列必须留空而不是写「不适用」。
    """
    import pandas as pd
    import pyarrow as pa

    from src.engine.emission_factors import get_all_factors

    factors = get_all_factors()
    rows = [
        {
            "车型": name,
            "燃料类型": data["fuel_type"],
            "CO2 排放因子（kg/km）": data["co2_kg_per_km"],
            "年均里程参考（km）": f"{data['avg_annual_km']:,}",
        }
        for name, data in factors.items()
    ]
    frame = pd.DataFrame(rows)
    table = pa.Table.from_pandas(frame)
    assert table.num_rows == len(factors)


def test_factor_table_source_keeps_numeric_column_clean():
    """守卫源码：油耗列不得再用 `or "..."` 这种字符串回落。

    断言针对赋值表达式而不是任意出现，否则注释里提到「不适用」也会被误判。
    """
    source = io.open("src/ui/views/overview.py", encoding="utf-8").read()
    assert '"油耗参考（L/100km）": data.get("fuel_consumption_l_per_100km") or "' not in source
    assert "油耗说明" in source
    assert "NumberColumn" in source

class TestHumanizeDetailAgainstRealPydanticMessages:
    """回归：翻译必须覆盖 Pydantic v2 的真实 msg 文本，而不是我臆想的措辞。

    下面这些 detail 都是从运行中的 ``/api/calculate`` 抓下来的原样结构。
    """

    def test_empty_list_says_item_count_not_character_count(self):
        detail = [
            {
                "type": "too_short",
                "loc": ["body", "fleet"],
                "msg": "List should have at least 1 item after validation, not 0",
                "input": [],
                "ctx": {"field_type": "List", "min_length": 1, "actual_length": 0},
            }
        ]
        text = _humanize_detail(detail)
        assert text == "车队清单至少需要 1 项"
        assert "字符" not in text

    def test_field_required_is_translated(self):
        detail = [
            {
                "type": "missing",
                "loc": ["body", "fleet"],
                "msg": "Field required",
                "input": {"company_name": "测试"},
            }
        ]
        assert _humanize_detail(detail) == "缺少必填项：车队清单"

    def test_value_error_prefix_is_stripped(self):
        detail = [
            {
                "type": "value_error",
                "loc": ["body", "fleet", 0, "vehicle_type"],
                "msg": "Value error, 不支持的车型: 飞碟",
                "input": "飞碟",
            }
        ]
        text = _humanize_detail(detail)
        assert text == "不支持的车型: 飞碟"
        assert "Value error" not in text

    def test_numeric_bounds_read_as_sentences(self):
        detail = [
            {"loc": ["body", "fleet", 0, "annual_km"], "msg": "Input should be less than or equal to 300000.0", "ctx": {"le": 300000.0}},
            {"loc": ["body", "fleet", 0, "count"], "msg": "Input should be greater than 0", "ctx": {"gt": 0}},
        ]
        text = _humanize_detail(detail)
        assert "年均里程不能超过 300000.0" in text
        assert "车辆数必须大于 0" in text

    def test_input_and_ctx_are_never_echoed(self):
        secret = "张三物流" * 40
        detail = [
            {
                "type": "string_too_long",
                "loc": ["body", "company_name"],
                "msg": "String should have at most 100 characters",
                "input": secret,
                "ctx": {"max_length": 100},
            }
        ]
        text = _humanize_detail(detail)
        assert secret not in text
        assert text == "企业名称最多 100 个字符"

    def test_unmapped_field_still_readable(self):
        detail = [
            {"loc": ["body", "totally_unknown"], "msg": "Field required"},
        ]
        text = _humanize_detail(detail)
        assert "totally_unknown" in text
        assert "Field required" not in text

class TestUiProcessReadsDotenv:
    """第 11 轮评审的 P0-1：前端是独立进程，必须自己加载 .env。

    实测复现路径：把 APP_API_KEY 写进 .env → 后端 API_KEY 非空、
    /api/health 的 security.mode = protected；但 src/ui/api_client.py 直接
    os.getenv，而全仓只有 src/config.py 调用 load_dotenv()、只有 src/api/main.py
    导入 src.config → 前端拿到 None、API_HEADERS == {}，界面上每个请求 401，
    且界面里没有任何一句解释。
    """

    def test_api_client_imports_config_so_dotenv_is_loaded(self):
        source = (Path(__file__).resolve().parents[1] / "src" / "ui" / "api_client.py").read_text(
            encoding="utf-8"
        )
        assert "import src.config" in source, "api_client 必须 import src.config 才会触发 load_dotenv()"
        # 且必须在读 getenv 之前
        assert source.index("import src.config") < source.index("API_BASE_URL = ")

    def test_env_key_lands_in_headers_in_a_fresh_process(self, tmp_path):
        """全新解释器里，只要进程环境有 APP_API_KEY，API_HEADERS 就必须带上它。

        注意这里**不能**把 .env 本身当成被测对象：src/config.py 现在把 dotenv
        锚定到仓库根目录的 .env（裸 load_dotenv() 会随 cwd 漂移），所以在任意
        临时目录放一个 .env 是不该被读到的。.env → 进程环境这一段由
        test_config_anchors_dotenv_to_repo_root 单独守。
        """
        repo = Path(__file__).resolve().parents[1]
        script = (
            "import os, sys\n"
            f"sys.path.insert(0, r'{repo}')\n"
            "from src.ui import api_client\n"
            "assert 'X-API-Key' in api_client.API_HEADERS, api_client.API_HEADERS\n"
            "assert api_client.API_HEADERS['X-API-Key'] == 'probe-key-should-be-in-header'\n"
            "print('OK')\n"
        )
        probe = tmp_path / "probe.py"
        probe.write_text(script, encoding="utf-8")
        env = dict(os.environ)
        env["APP_API_KEY"] = "probe-key-should-be-in-header"
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        result = subprocess.run(
            [sys.executable, str(probe)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            cwd=str(tmp_path),
        )
        assert result.returncode == 0, result.stderr
        assert "OK" in result.stdout

    def test_auth_failure_has_actionable_hint(self):
        from src.ui.api_client import _auth_failure_hint

        for status in (401, 403):
            hint = _auth_failure_hint(status)
            assert "APP_API_KEY" in hint
            assert ".env" in hint
            assert "重启" in hint
            assert "security.mode" in hint


def test_config_anchors_dotenv_to_repo_root():
    """``load_dotenv()`` 不带路径时是按当前工作目录往上层找 .env。

    Streamlit / IDE / CI 的工作目录不一定是仓库根，实测只改 cwd 就会让
    APP_API_KEY 读不到、前端每个接口 401，所以必须锚定到仓库根。
    """
    repo = Path(__file__).resolve().parents[1]
    source = (repo / "src" / "config.py").read_text(encoding="utf-8")
    assert "load_dotenv(dotenv_path=" in source
    assert '.env' in source
