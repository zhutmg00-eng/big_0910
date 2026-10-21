"""Small, shared HTTP client for the Streamlit views."""

import os
from urllib.parse import urlparse

import requests
import streamlit as st

# 用 `or` 而非 getenv 默认值：环境变量存在但为空字符串（Compose 常见）时也回退到默认地址
API_BASE_URL = (os.getenv("API_BASE_URL") or "http://localhost:8000").rstrip("/")
API_TIMEOUT = float(os.getenv("API_TIMEOUT") or 60)
APP_API_KEY = os.getenv("APP_API_KEY") or ""
API_HEADERS = {"X-API-Key": APP_API_KEY} if APP_API_KEY else {}

_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0", "api"}

_session = requests.Session()
# 本机 / Compose 内网地址不走系统代理：校园网、公司网或 Clash 等全局代理
# 会把 localhost 请求转发出去，导致“后端明明在跑却返回 404/502”。
if (urlparse(API_BASE_URL).hostname or "") in _LOCAL_HOSTS:
    _session.trust_env = False


def api_post(path: str, payload: dict) -> requests.Response:
    """Call a backend endpoint with a bounded timeout."""
    return _session.post(f"{API_BASE_URL}{path}", json=payload, headers=API_HEADERS, timeout=API_TIMEOUT)


def api_get(path: str) -> requests.Response:
    return _session.get(f"{API_BASE_URL}{path}", headers=API_HEADERS, timeout=API_TIMEOUT)


def show_api_error(response: requests.Response) -> None:
    """Render the backend's most useful error detail."""
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    st.error(f"请求未完成（{response.status_code}）：{_humanize_detail(detail)}")


#: 后端 Pydantic 字段名 → 用户可读的中文字段名。
#: 只用于把「校验失败」翻译成人话；未登记的字段回退到字段名本身。
_FIELD_LABELS = {
    "company_name": "企业名称",
    "fleet": "车队清单",
    "vehicle_type": "车型",
    "count": "车辆数",
    "annual_km": "年均里程",
    "load_factor": "满载率",
    "companies": "对比企业",
    "question": "问题",
    "diesel_price_yuan_per_l": "柴油单价",
    "electricity_price_yuan_per_kwh": "电价",
}


def _humanize_detail(detail) -> str:
    """把 FastAPI/Pydantic 的校验错误翻译成一句人话。

    背景：``st.error(f"...{detail}")`` 在 422 时会把整块 ``list[dict]``
    原样打印出来（含 ``input`` 里的全部用户输入与 ``ctx`` 内部结构），
    实测输入 200 字企业名时屏幕上是一大段 Python 字典。这里逐条取
    ``msg`` 并按 ``loc`` 映射成中文，**绝不回显 ``input``/``ctx``**。
    """
    if not isinstance(detail, list):
        return str(detail)
    messages = []
    for item in detail:
        if not isinstance(item, dict):
            messages.append(str(item))
            continue
        msg = str(item.get("msg") or "").strip()
        loc = [part for part in (item.get("loc") or []) if isinstance(part, str)]
        field = next((p for p in reversed(loc) if p in _FIELD_LABELS), None)
        if field:
            label = _FIELD_LABELS[field]
            if "at most" in msg:
                limit = (item.get("ctx") or {}).get("max_length")
                msg = f"{label}最多 {limit} 个字符" if limit else f"{label}过长"
            elif "at least" in msg:
                limit = (item.get("ctx") or {}).get("min_length")
                msg = f"{label}至少 {limit} 个字符" if limit else f"{label}过短"
            elif "greater than" in msg:
                msg = f"{label}必须大于 {(item.get('ctx') or {}).get('gt', 0)}"
            elif "less than or equal" in msg:
                msg = f"{label}不能超过 {(item.get('ctx') or {}).get('le', '')}".strip()
            elif "missing" in msg:
                msg = f"缺少必填项：{label}"
            else:
                msg = f"{label}：{msg}"
        elif msg:
            msg = f"参数格式不正确：{msg}"
        if msg:
            messages.append(msg)
    if not messages:
        return "提交的内容未通过校验，请检查后重试"
    return "；".join(messages)
