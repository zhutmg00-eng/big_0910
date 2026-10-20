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
    st.error(f"请求未完成（{response.status_code}）：{detail}")
