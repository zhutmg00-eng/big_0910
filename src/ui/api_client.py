"""Small, shared HTTP client for the Streamlit views."""

import os
from urllib.parse import urlparse

import requests
import streamlit as st

import src.config  # noqa: F401  # 必须最先导入：src.config 是唯一调用 load_dotenv() 的地方

# 【必须 import src.config，不能只读 os.getenv】
# 前端是独立的 Streamlit 进程，此前全仓只有 src/api/main.py 一侧 import src.config，
# 而 src/config.py 才是唯一调用 load_dotenv() 的地方。结果：用户照 README 把
# APP_API_KEY 写进 .env 后，后端读到了（posture=protected），前端 `os.getenv`
# 拿到 None、API_HEADERS == {}，于是界面上每个请求都 401，而界面上看不到任何解释。
# 用 dotted import 而不是 from src.config import ...：保证 config 先于下面的
# getenv 完成 load_dotenv，不依赖导入顺序。

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
    # 404/502/503 先分诊：本机 8000 端口常被别的进程（node 服务、旧版本、
    # 别的课的项目）占着，此时后端根本没起来，浏览器却能连上，前端会把
    # 陌生服务的 {"message": "Route POST:/api/calculate not found"} 原样
    # 渲染成「请求未完成（404）：Route POST:/api/calculate not found」——
    # 用户看到的是路由名，而不是「你的后端没起来」。
    if response.status_code in _BACKEND_MISSING_STATUS:
        st.error(_backend_missing_hint(response.status_code))
        return
    if response.status_code in _AUTH_FAILURE_STATUS:
        # 401/403 单独给话术：绝大多数情况下不是「代码错了」，而是前端与后端
        # 用的 key 不一致（或前端根本没读到 .env）。原样渲染 detail 只会显示
        # 「请求未完成（401）：Missing or invalid X-API-Key」，用户无从下手。
        st.error(_auth_failure_hint(response.status_code))
        return
    try:
        detail = response.json().get("detail", response.text)
    except ValueError:
        detail = response.text
    st.error(f"请求未完成（{response.status_code}）：{_humanize_detail(detail)}")


#: 这几个状态码在「前端连上了某个服务」的前提下基本只有一种解释：
#: 端口上跑的不是本项目后端（或后端在重启）。统一走分诊提示。
_BACKEND_MISSING_STATUS = (404, 502, 503, 504)


def _describe_backend_down(exc: requests.RequestException) -> str:
    """把连接类异常翻译成「后端没起来 / 端口被占用」。

    ``requests`` 的原生报错是 ``HTTPConnectionPool(host='localhost',
    port=8000): Max retries exceeded ... Errno 10061``，对车队老板毫无意义。
    """
    reason = type(exc).__name__
    return (
        f"连不上核算服务（{API_BASE_URL}，{reason}）。\n\n"
        "常见原因有两个：① 后端没启动 —— 另开一个终端执行 "
        "`python -m uvicorn src.api.main:app --port 8000`；"
        "② 8000 端口被别的程序占用 —— 换端口启动后端，并设置环境变量 "
        "`API_BASE_URL` 指向新端口。"
    )


#: 鉴权失败。前端与后端的 key 不一致时几乎必然出现，且用户看不出原因。
_AUTH_FAILURE_STATUS = (401, 403)


def _auth_failure_hint(status_code: int) -> str:
    """把 401/403 翻译成「前后端 key 不一致」的排查步骤。

    实测场景：用户照 README 把 ``APP_API_KEY`` 写进 ``.env``，后端读到了
    （``/api/health`` 的 security.mode = ``protected``），但前端进程没读到，
    于是每个请求都 401，而界面只显示一句「请求未完成（401）」。
    """
    state = "已设置（应已随请求发送）" if APP_API_KEY else "未设置（请求里没有 X-API-Key 头）"
    return (
        f"核算服务拒绝了本次请求（HTTP {status_code}）。\n\n"
        f"**当前界面发起请求时的 API key 状态：{state}**\n\n"
        "前后端必须用同一个 APP_API_KEY：\n"
        "1. 在项目根目录的 `.env` 里写 `APP_API_KEY=你的口令`（该文件已被 .gitignore 排除）；\n"
        "2. **重启 Streamlit 与 uvicorn 两个进程**（.env 只在进程启动时读取）；\n"
        f"3. 打开 {API_BASE_URL}/api/health，看 `security.mode` 是 `protected` 还是 `open_dev`；\n"
        "4. 若后端是 `protected` 而界面仍报 401，说明界面进程没读到 `.env` —— "
        "请确认是在项目根目录启动的 `python -m streamlit run src/ui/app.py`。"
    )


def _backend_missing_hint(status_code: int) -> str:
    return (
        f"核算服务返回 {status_code}，说明 {API_BASE_URL} 上跑的不是本项目后端"
        "（端口多半被别的程序占用了）。\n\n"
        "请换一个端口启动后端，例如 `python -m uvicorn src.api.main:app --port 8010`，"
        "并设置环境变量 `API_BASE_URL=http://localhost:8010` 后重启界面。"
    )



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
            elif "field required" in msg.lower() or "missing" in msg:
                msg = f"缺少必填项：{label}"
            elif "at least" in msg and "list" in msg.lower():
                limit = (item.get("ctx") or {}).get("min_length")
                msg = f"{label}至少需要 {limit} 项" if limit else f"{label}不能为空"
            elif "at least" in msg:
                limit = (item.get("ctx") or {}).get("min_length")
                msg = f"{label}至少 {limit} 个字符" if limit else f"{label}过短"
            elif "greater than" in msg:
                msg = f"{label}必须大于 {(item.get('ctx') or {}).get('gt', 0)}"
            elif "less than or equal" in msg:
                msg = f"{label}不能超过 {(item.get('ctx') or {}).get('le', '')}".strip()
            elif msg.startswith("Value error, "):
                # Pydantic v2 会把 ValueError 的原文前置这段英文，
                # 例如「Value error, 不支持的车型: 飞碟」，用户看不懂。
                msg = msg[len("Value error, ") :].strip()
            elif "valid list" in msg or "valid tuple" in msg:
                msg = f"{label}格式不正确，应为一个列表"
            elif "valid integer" in msg:
                msg = f"{label}应为整数"
            elif "valid number" in msg or "valid float" in msg:
                msg = f"{label}应为数字"
            else:
                msg = f"{label}：{msg}"
        elif "field required" in msg.lower() or "missing" in msg:
            # 未登记字段也要说清「缺哪一项」，不能只丢一句 Field required。
            hint = ".".join(loc) or "请求体"
            msg = f"缺少必填项：{hint}"
        elif msg.startswith("Value error, "):
            msg = msg[len("Value error, ") :].strip() or "提交的内容未通过校验"
        elif msg:
            msg = f"参数格式不正确：{msg}"
        if msg:
            messages.append(msg)
    if not messages:
        return "提交的内容未通过校验，请检查后重试"
    return "；".join(messages)
