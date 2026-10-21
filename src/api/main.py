"""FastAPI 后端服务入口

安全措施：
- CORS限制为可信来源（可通过环境变量配置）
- API key鉴权（X-API-Key header）
- 文件路径校验（防止路径遍历攻击）
"""
import logging
import os
import secrets
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Depends, Request, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from pathlib import Path

from src.models.fleet import FleetInput
from src.models.policy import PolicyAnswer, PolicyQuestion
from src.models.tco import VehicleTCORunRequest
from src.models.uncertainty import UncertaintyRequest

APP_VERSION = "0.4.2"
logger = logging.getLogger("carbon_api")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"),
                    format="%(asctime)s %(levelname)s %(name)s %(message)s")


@asynccontextmanager
async def lifespan(_: FastAPI):
    """启动时可选自动建库（KB_AUTO_INGEST=1），首次部署无需手动执行入库脚本。"""
    _posture = build_security_posture()
    if not _posture["auth_required"]:
        # 用 warning 级别而不是 info：无鉴权上线是被明确禁止的部署形态，
        # 默认日志级别下也必须看得见。
        logger.warning("安全自检：%s", _posture["warning"])
    if os.getenv("KB_AUTO_INGEST", "0") == "1":
        try:
            from src.config import POLICY_DOCS_DIR
            from src.rag import ingest_directory
            from src.rag.vector_store import get_vector_store

            vs = get_vector_store()
            if vs.count() == 0:
                logger.info("知识库为空，开始自动入库 %s", POLICY_DOCS_DIR)
                logger.info("自动入库完成: %s", ingest_directory(POLICY_DOCS_DIR, vs))
        except Exception:  # 建库失败不应阻止计算类接口启动
            logger.exception("知识库自动入库失败，政策问答将不可用")
    yield


app = FastAPI(
    title="物流碳排放与减排情景决策助手 API",
    version=APP_VERSION,
    description="面向物流企业的科研原型：直接运营排放核算、不确定性分析、减排情景与政策检索",
    lifespan=lifespan,
)


@app.middleware("http")
async def request_context(request: Request, call_next):
    """为每个请求分配 X-Request-ID 并记录耗时，便于排查与性能评估。"""
    rid = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:12]
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["X-Request-ID"] = rid
    response.headers["X-Process-Time-ms"] = f"{elapsed:.1f}"
    if request.url.path.startswith("/api/") and request.url.path != "/api/health":
        logger.info("%s %s %s %.1fms rid=%s", request.method, request.url.path,
                    response.status_code, elapsed, rid)
    return response


# ============================================================
# CORS配置（可通过环境变量配置允许的来源）
# ============================================================
ALLOWED_ORIGINS = (os.getenv("CORS_ORIGINS") or "http://localhost:8501,http://localhost:3000").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in ALLOWED_ORIGINS if o.strip()],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# ============================================================
# API Key鉴权
# ============================================================
API_KEY = os.getenv("APP_API_KEY", "")  # 不设则为开发模式（不鉴权）
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


# 常见占位值：直接照抄 .env.example 就会得到这些。它们不是密钥，
# 但若被当成密钥通过「已配置」判断，服务会进入"看起来受保护、实际人人可过"的状态。
_PLACEHOLDER_KEYS = frozenset({
    "your-api-key-here",
    "changeme",
    "change-me",
    "sk-xxx",
    "xxx",
    "dev-key",
    "test",
    "placeholder",
})


def build_security_posture(api_key: str | None = None) -> dict:
    """把「当前是否在无鉴权状态下运行」变成可查询的事实。

    未设 APP_API_KEY 时全部端点（含 POST /api/kb/ingest-all 这类会重建知识库的
    写操作）都无需凭证即可调用。这个行为本身是为了本地开发方便，但它是隐性的：
    运维只看到 200，看不出自己正裸奔。README 里写了警告，程序里却没有任何出口
    能自证状态，所以这里给出结构化自检，并由 /api/health 与启动日志输出。

    占位值（your-api-key-here 等）与未设置同等对待：照抄 .env.example 是常见做法，
    此时若判为"已配置"，鉴权等于用一个公开字符串把关，比不设更危险。
    """
    key = API_KEY if api_key is None else api_key
    normalized = (key or "").strip()
    if normalized.lower() in _PLACEHOLDER_KEYS:
        return {
            "auth_required": False,
            "mode": "placeholder_key",
            "warning": (
                f"APP_API_KEY 的值是占位符「{normalized}」，不是真实密钥。实际效果等同于未鉴权："
                "任何人照抄 .env.example 即可通过校验。请生成随机密钥后重新启动。"
            ),
        }
    if normalized:
        return {
            "auth_required": True,
            "mode": "protected",
            "warning": "",
        }
    return {
        "auth_required": False,
        "mode": "open_dev",
        "warning": (
            "APP_API_KEY 未设置：所有端点（含会重建知识库的 POST /api/kb/ingest-all）"
            "当前无需凭证即可调用。仅供本机开发；对外演示请改用 docker-compose.prod.yml "
            "或显式设置 APP_API_KEY。"
        ),
    }


async def verify_api_key(api_key: str = Security(api_key_header)):
    """验证API Key（如果配置了APP_API_KEY则强制校验，否则开发模式跳过）"""
    if API_KEY:  # 生产模式：需要校验
        if not api_key or not secrets.compare_digest(api_key, API_KEY):  # 常量时间比较，防计时攻击
            raise HTTPException(status_code=401, detail="Invalid or missing API key")
    # 开发模式（未设API_KEY）：跳过鉴权
    return api_key


# ============================================================
# 安全路径校验
# ============================================================
def safe_resolve_path(file_path: str, base_dir: Path) -> Path:
    """安全解析文件路径，防止路径遍历攻击"""
    base_dir = base_dir.resolve()
    requested = Path(file_path).resolve()
    # 确保解析后的路径在base_dir内
    if not requested.is_relative_to(base_dir):
        raise HTTPException(
            status_code=403,
            detail=f"Access denied: path must be within {base_dir}"
        )
    return requested


# ============================================================
# 注册路由
# ============================================================
from src.api.routes_compare import router as compare_router
app.include_router(compare_router)


# ========== 数据模型 ==========

class CarbonResult(BaseModel):
    company_name: str
    total_emission_t: float
    total_vehicles: int
    emission_by_type: dict
    carbon_budget: dict
    scenario_cost: dict
    methodology_note: str

# ========== API路由 ==========

@app.get("/api/health")
def health_check():
    return {"status": "ok", "version": APP_VERSION, "security": build_security_posture()}


@app.get("/api/kb/health")
def kb_health():
    """知识库健康自检：回答"政策问答为什么是空的"。

    独立于 /api/health（后者只表示进程活着）。按需懒加载，不阻塞服务启动。
    status: ok / empty / degraded；warning 非空时可直接展示给用户。
    """
    from src.rag.vector_store import get_vector_store

    return get_vector_store().health()


@app.get("/api/vehicle-types")
def get_vehicle_types(api_key: str = Depends(verify_api_key)):
    """获取支持的车型列表"""
    from src.engine.emission_factors import get_all_factors
    factors = get_all_factors()
    return {
        "vehicle_types": [
            {
                "name": name,
                "fuel_type": data["fuel_type"],
                "co2_kg_per_km": data["co2_kg_per_km"],
                "avg_annual_km": data["avg_annual_km"],
            }
            for name, data in factors.items()
        ]
    }


@app.post("/api/calculate", response_model=CarbonResult)
def calculate_carbon(fleet_input: FleetInput, api_key: str = Depends(verify_api_key)):
    """计算直接运营排放基线、模拟碳预算差额和情景成本。"""
    from src.engine.calculator import VehicleGroupData, calculate_emission
    from src.engine.quota import estimate_quota_gap
    from src.engine.carbon_price import estimate_compliance_cost, load_carbon_price_data

    # 1. 转换输入
    fleet = [
        VehicleGroupData(
            vehicle_type=v.vehicle_type,
            count=v.count,
            annual_km=v.annual_km,
            load_factor=v.load_factor,
        )
        for v in fleet_input.fleet
    ]

    # 2. 计算碳排放基线
    baseline = calculate_emission(fleet)

    # 3. 构建车队摘要 → 估算模拟碳预算差额
    fleet_summary = {}
    for v in fleet_input.fleet:
        fleet_summary[v.vehicle_type] = fleet_summary.get(v.vehicle_type, 0) + v.count

    gap = estimate_quota_gap(
        baseline.total_emission_t,
        fleet_summary,
        reduction_target=fleet_input.scenario_reduction_target,
        fleet_groups=fleet,
    )

    # 4. 加载碳价数据 → 估算成本
    price_df = load_carbon_price_data()
    cost = estimate_compliance_cost(gap.gap_t, price_df)

    budget_scope_note = "科研原型估算，不是法定配额或履约依据"
    if gap.caliber_note:
        budget_scope_note = f"{budget_scope_note}；{gap.caliber_note}"

    return CarbonResult(
        company_name=fleet_input.company_name,
        total_emission_t=baseline.total_emission_t,
        total_vehicles=baseline.total_vehicles,
        emission_by_type=baseline.emission_by_type,
        carbon_budget={
            "模拟碳预算_t": gap.total_quota_t,
            "预算差额_t": gap.gap_t,
            "状态": gap.gap_status,
            "分车型预算": gap.quota_by_type,
            "情景减排目标": gap.reduction_target,
            "活动水平偏离_pct": gap.activity_mismatch_pct,
            "口径说明": budget_scope_note,
        },
        scenario_cost=cost,
        methodology_note=(
            "当前仅核算车辆直接运营排放；新能源物流车的购电间接排放及车辆全生命周期排放未计入。"
        ),
    )


@app.post("/api/ask", response_model=PolicyAnswer)
def ask_policy(question: PolicyQuestion, api_key: str = Depends(verify_api_key)):
    """碳交易政策智能问答"""
    from src.rag import PolicyAdvisor

    t0 = time.perf_counter()
    result = PolicyAdvisor().ask(question.question, question.carbon_profile)
    return PolicyAnswer(
        question=result["question"],
        retrieved_sources=result["retrieved_sources"],
        answer=result["answer"],
        evidence_count=result.get("evidence_count", len(result["retrieved_sources"])),
        evidence_warning=result.get("evidence_warning", ""),
        latency_ms=round((time.perf_counter() - t0) * 1000, 1),
    )


@app.get("/api/kb/stats")
def kb_stats(api_key: str = Depends(verify_api_key)):
    """知识库统计"""
    from src.rag.vector_store import get_vector_store
    return get_vector_store().get_stats()


@app.post("/api/kb/ingest")
def ingest_document(
    file_path: str,
    doc_date: str = "",
    api_key: str = Depends(verify_api_key),
):
    """导入一份政策文档到知识库

    安全措施：file_path必须位于项目data目录内，防止路径遍历攻击
    """
    from src.config import POLICY_DOCS_DIR
    from src.rag import PolicyAdvisor

    # 安全校验：确保文件路径在policy_docs目录内
    safe_path = safe_resolve_path(file_path, POLICY_DOCS_DIR)
    if not safe_path.exists():
        raise HTTPException(status_code=404, detail=f"File not found: {file_path}")

    advisor = PolicyAdvisor()
    count = advisor.ingest_document(str(safe_path), doc_date)
    return {"file": safe_path.name, "chunks_added": count}


@app.post("/api/kb/ingest-all")
def ingest_all_documents(force: bool = False, api_key: str = Depends(verify_api_key)):
    """批量导入 data/policy_docs 下全部政策文档（幂等）。"""
    from src.config import POLICY_DOCS_DIR
    from src.rag import ingest_directory

    return ingest_directory(POLICY_DOCS_DIR, force=force)


@app.post("/api/uncertainty")
def emission_uncertainty(payload: UncertaintyRequest, api_key: str = Depends(verify_api_key)):
    """蒙特卡洛排放不确定性分析：P5/P50/P95 区间与方差贡献排序。"""
    from dataclasses import asdict
    from src.engine.calculator import VehicleGroupData
    from src.engine.uncertainty import monte_carlo_emission

    fleet = [VehicleGroupData(v.vehicle_type, v.count, v.annual_km, v.load_factor) for v in payload.fleet]
    try:
        res = monte_carlo_emission(
            fleet,
            n_samples=payload.n_samples,
            seed=payload.seed,
            data_quality=payload.data_quality,
            load_delta=payload.load_delta,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return asdict(res)


@app.get("/api/tco/defaults")
def get_tco_defaults(api_key: str = Depends(verify_api_key)):
    """获取所有车型的 TCO 基准参数与宏观经济默认参数"""
    from dataclasses import asdict
    from src.engine.tco import DEFAULT_TCO_BENCHMARKS, TCOEconomicParameters
    return {
        "benchmarks": {k: asdict(v) for k, v in DEFAULT_TCO_BENCHMARKS.items()},
        "economic_parameters": asdict(TCOEconomicParameters()),
    }


@app.post("/api/tco/calculate")
def calculate_tco_endpoint(payload: VehicleTCORunRequest, api_key: str = Depends(verify_api_key)):
    """计算单个车型新能源替代的 TCO 经济账与投资回收期"""
    from dataclasses import asdict
    from src.engine.tco import (
        DEFAULT_TCO_BENCHMARKS,
        TCOEconomicParameters,
        VehicleTCOBenchmark,
        calculate_single_vehicle_tco,
        get_tco_benchmark,
    )

    spec = get_tco_benchmark(payload.vehicle_type)
    if spec is None:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的车型: {payload.vehicle_type}，支持的车型: {list(DEFAULT_TCO_BENCHMARKS.keys())}",
        )

    if payload.ev_vehicle_price_wan is not None:
        spec = VehicleTCOBenchmark(
            ice_vehicle_price_wan=spec.ice_vehicle_price_wan,
            ev_vehicle_price_wan=payload.ev_vehicle_price_wan,
            charger_cost_wan=spec.charger_cost_wan,
            fuel_consumption_per_100km=spec.fuel_consumption_per_100km,
            electricity_consumption_per_100km=spec.electricity_consumption_per_100km,
            fuel_type=spec.fuel_type,
            annual_maintenance_ice_yuan=spec.annual_maintenance_ice_yuan,
            maintenance_saving_ratio=spec.maintenance_saving_ratio,
        )

    # 用 is None 判断而非 or：模型层虽是 gt=0，但 or 会把合法的 0.0 静默替换成
    # 默认值，一旦字段校验放宽就会出现「输入被悄悄改写」的静默错误。
    econ = TCOEconomicParameters(
        diesel_price_yuan_per_l=(
            payload.diesel_price_yuan_per_l
            if payload.diesel_price_yuan_per_l is not None
            else 7.50
        ),
        electricity_price_yuan_per_kwh=(
            payload.electricity_price_yuan_per_kwh
            if payload.electricity_price_yuan_per_kwh is not None
            else 0.80
        ),
        lifespan_years=(
            payload.lifespan_years if payload.lifespan_years is not None else 5
        ),
        is_baas_mode=payload.is_baas_mode,
        baas_chassis_discount_wan=(
            payload.baas_chassis_discount_wan
            if payload.baas_chassis_discount_wan is not None
            else 0.0
        ),
        baas_annual_battery_rental_yuan=(
            payload.baas_annual_battery_rental_yuan
            if payload.baas_annual_battery_rental_yuan is not None
            else 0.0
        ),
    )

    res = calculate_single_vehicle_tco(
        vehicle_type=payload.vehicle_type,
        replace_count=payload.replace_count,
        annual_km=payload.annual_km,
        annual_co2_reduction_t=payload.annual_co2_reduction_t,
        custom_benchmark=spec,
        econ_params=econ,
    )

    return asdict(res)
