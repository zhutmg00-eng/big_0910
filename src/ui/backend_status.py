"""侧栏里的后端连通性状态条。

为什么单独做一个模块：界面有 7 个页面，每个页面各自发请求、各自报错。
后端没启动时用户要先点一次「计算」等两三秒才知道，而且看到的错误分散在
各页面的错误框里，无法判断「是我填错了」还是「服务根本没起来」。

这里把三件与页面无关的事集中起来：
1. 探测后端（1.5 秒超时，不让界面等 60 秒）；
2. 记住上一次探测结果，避免每次重跑脚本都打网络请求；
3. 渲染成侧栏一行状态 + 可展开的成因说明。
"""

import time
from typing import Dict

import streamlit as st

from src.ui.api_client import API_BASE_URL, _session

#: 状态条自己的探测超时（秒）。**不能**用 API_TIMEOUT：模型冷启动要几秒，
#: 但侧栏只想回答「有没有人在 8000 端口上应答」，1.5 秒足够，且失败后界面
#: 仍然可用（只是提示后端未就绪）。
PROBE_TIMEOUT = 1.5

#: 两次探测之间的最小间隔（秒）。Streamlit 每次交互都会重跑整个脚本，
#: 不加这个间隔会让侧栏每次点击都打一次 /api/health。
PROBE_CACHE_TTL = 10.0


def probe_backend(force: bool = False) -> Dict[str, object]:
    """探测 ``/api/health``，返回 ``{"ok", "status_code", "latency_ms", "detail"}``。"""
    now = time.monotonic()
    cached = st.session_state.get("_backend_probe")
    if not force and cached and (now - float(cached.get("at") or 0.0)) < PROBE_CACHE_TTL:
        return cached

    result: Dict[str, object] = {
        "ok": False,
        "status_code": None,
        "latency_ms": None,
        "detail": "",
        "at": now,
    }
    started = time.perf_counter()
    try:
        response = _session.get(f"{API_BASE_URL}/api/health", timeout=PROBE_TIMEOUT)
        result["latency_ms"] = round((time.perf_counter() - started) * 1000, 1)
        result["status_code"] = response.status_code
        if response.status_code == 200:
            payload = response.json()
            result["ok"] = True
            result["detail"] = str(payload.get("version") or "")
        else:
            result["detail"] = f"HTTP {response.status_code}"
    except Exception as exc:  # noqa: BLE001 - 探测失败的原因对用户只有两类，见下方渲染
        result["detail"] = type(exc).__name__
    st.session_state["_backend_probe"] = result
    return result


def render_backend_status() -> None:
    """在侧栏渲染一行状态。失败时给出可执行的两条排查路径。"""
    probe = probe_backend()
    if probe["ok"]:
        version = f" v{probe['detail']}" if probe["detail"] else ""
        st.sidebar.success(
            f"后端已连接{version}（{probe['latency_ms']} ms）",
            icon="✅",
        )
        return

    with st.sidebar:
        st.warning(
            f"后端未连接（{API_BASE_URL}）\n\n"
            "计算与问答现在点了会报错，先把后端启动起来：",
            icon="⚠️",
        )
        with st.expander("怎么启动 / 为什么连不上"):
            st.markdown(
                "**① 后端没启动**：另开一个终端在项目根目录执行\n"
                "```powershell\n"
                "python -m uvicorn src.api.main:app --port 8000\n"
                "```\n"
                "**② 8000 端口被别的程序占用**：uvicorn 只打一行 "
                "`[Errno 10048]` 就退出。改成别的端口，并让界面指过去\n"
                "```powershell\n"
                "python -m uvicorn src.api.main:app --port 8010\n"
                "$env:API_BASE_URL=\"http://localhost:8010\"\n"
                "python -m streamlit run src/ui/app.py\n"
                "```"
            )
            st.caption(f"最近一次探测：{probe['detail'] or '无应答'}（超时 {PROBE_TIMEOUT}s）")
