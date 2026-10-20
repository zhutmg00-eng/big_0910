"""排放基线不确定性分析（蒙特卡洛，IPCC 2006 Vol.1 Ch.3 Approach 2）。

动机
----
点估计 E = Σ n·d·EF·LF/1000 掩盖了两类主要不确定性：

1. **排放因子 EF**：同一车型在不同文献 / 标准中的取值差异明显（如轻型柴油货车
   在《中国环境科学》2021 为 0.374 kg/km，GB 30510-2024 限值折算仅 0.257）；
   LNG 重卡实测值 0.72~1.20 kg/km，甚至可能高于柴油车。
2. **活动水平**：企业填报的年均里程、满载率多为估计值而非台账值。

方法
----
- EF：若因子库中存在该车型的多来源取值（基准值 + 括号内细分 / 标准 / 实测变体），
  采用三角分布 Tri(min, mode=基准值, max)，并保证相对半宽不低于 ``ef_min_halfwidth``；
  否则采用正态分布 N(EF, (cv·EF)²)。零排放车型（新能源直接排放）不抽样。
- 年均里程：截断正态 N(d, (cv_km·d)²)，cv_km 由数据质量等级决定：
  台账/GPS = 5%，抽样统计 = 10%，经验估计 = 20%。
- 满载率：均匀分布 U(l-δ, l+δ)，截断到 [0, 1]。
- 车辆数视为确定值。
- 各车型 EF 视为相互独立；同一车型多组记录共用同一 EF 抽样（完全相关），
  这是 IPCC 推荐的保守处理。

输出 P5/P50/P95、相对不确定度 (P95-P5)/(2·均值)，以及基于 Spearman 秩相关平方
归一化的方差贡献（近似一阶敏感性指数），回答“先改进哪项数据最能降低不确定性”。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

import numpy as np

from src.engine.calculator import VehicleGroupData, calculate_emission
from src.engine.emission_factors import get_all_factors
from src.config import LOAD_FACTOR_ALPHA, LOAD_FACTOR_THRESHOLD

DATA_QUALITY_CV = {"台账": 0.05, "抽样": 0.10, "估计": 0.20}


@dataclass
class UncertaintyResult:
    point_estimate_t: float
    mean_t: float
    p5_t: float
    p50_t: float
    p95_t: float
    relative_uncertainty_pct: float
    n_samples: int
    seed: int
    contributions: Dict[str, float]
    ef_distributions: Dict[str, Dict]
    histogram: Dict[str, List[float]] = field(default_factory=dict)
    method: str = "Monte Carlo (IPCC 2006 Vol.1 Ch.3 Approach 2)"


def ef_range(vehicle_type: str, min_halfwidth: float = 0.10) -> Dict:
    """从因子库收集同一基础车型的多来源取值，返回三角分布参数。"""
    factors = get_all_factors()
    base = factors[vehicle_type]["co2_kg_per_km"]
    if base <= 0:
        return {"dist": "fixed", "mode": 0.0, "low": 0.0, "high": 0.0, "n_sources": 1}
    values = [base] + [
        f["co2_kg_per_km"]
        for name, f in factors.items()
        if name != vehicle_type and name.startswith(vehicle_type + "(") and f["co2_kg_per_km"] > 0
    ]
    low, high = min(values), max(values)
    low = min(low, base * (1 - min_halfwidth))
    high = max(high, base * (1 + min_halfwidth))
    return {
        "dist": "triangular" if len(values) > 1 else "triangular(default±%d%%)" % round(min_halfwidth * 100),
        "mode": base, "low": round(low, 4), "high": round(high, 4), "n_sources": len(values),
    }


def _load_adjustment(load: np.ndarray) -> np.ndarray:
    return np.where(load < LOAD_FACTOR_THRESHOLD, 1 + LOAD_FACTOR_ALPHA * (LOAD_FACTOR_THRESHOLD - load), 1.0)


def _spearman(x: np.ndarray, y: np.ndarray) -> float:
    if np.std(x) == 0 or np.std(y) == 0:
        return 0.0
    rx = np.argsort(np.argsort(x))
    ry = np.argsort(np.argsort(y))
    return float(np.corrcoef(rx, ry)[0, 1])


def monte_carlo_emission(
    fleet: List[VehicleGroupData],
    n_samples: int = 10000,
    seed: int = 2026,
    data_quality: str = "抽样",
    km_cv: float | None = None,
    load_delta: float = 0.05,
    ef_min_halfwidth: float = 0.10,
    bins: int = 40,
) -> UncertaintyResult:
    if not fleet:
        raise ValueError("车队不能为空")
    if n_samples < 100 or n_samples > 200000:
        raise ValueError("抽样次数应在 100~200000 之间")
    cv = km_cv if km_cv is not None else DATA_QUALITY_CV.get(data_quality, 0.10)
    rng = np.random.default_rng(seed)

    point = calculate_emission(fleet).total_emission_t
    total = np.zeros(n_samples)
    inputs: Dict[str, np.ndarray] = {}
    ef_samples: Dict[str, np.ndarray] = {}
    ef_dists: Dict[str, Dict] = {}

    for idx, g in enumerate(fleet):
        if g.vehicle_type not in ef_samples:
            dist = ef_range(g.vehicle_type, ef_min_halfwidth)
            ef_dists[g.vehicle_type] = dist
            if dist["dist"] == "fixed":
                ef_samples[g.vehicle_type] = np.zeros(n_samples)
            else:
                ef_samples[g.vehicle_type] = rng.triangular(dist["low"], dist["mode"], dist["high"], n_samples)
                inputs[f"排放因子·{g.vehicle_type}"] = ef_samples[g.vehicle_type]
        ef = ef_samples[g.vehicle_type]
        km = np.clip(rng.normal(g.annual_km, cv * g.annual_km, n_samples), 0, None)
        load = np.clip(rng.uniform(g.load_factor - load_delta, g.load_factor + load_delta, n_samples), 0, 1)
        emission = g.count * km * ef * _load_adjustment(load) / 1000
        total += emission
        if ef_dists[g.vehicle_type]["dist"] != "fixed":
            label = g.vehicle_type if sum(x.vehicle_type == g.vehicle_type for x in fleet) == 1 else f"{g.vehicle_type}#{idx + 1}"
            inputs[f"年均里程·{label}"] = km
            if g.load_factor - load_delta < LOAD_FACTOR_THRESHOLD:
                inputs[f"满载率·{label}"] = load

    rho2 = {name: _spearman(arr, total) ** 2 for name, arr in inputs.items()}
    s = sum(rho2.values()) or 1.0
    contributions = dict(sorted(((k, round(v / s, 4)) for k, v in rho2.items() if v / s >= 0.001),
                                key=lambda kv: kv[1], reverse=True))

    mean = float(total.mean())
    p5, p50, p95 = (float(v) for v in np.percentile(total, [5, 50, 95]))
    counts, edges = np.histogram(total, bins=bins)
    return UncertaintyResult(
        point_estimate_t=round(point, 2),
        mean_t=round(mean, 2),
        p5_t=round(p5, 2),
        p50_t=round(p50, 2),
        p95_t=round(p95, 2),
        relative_uncertainty_pct=round((p95 - p5) / 2 / mean * 100, 2) if mean > 0 else 0.0,
        n_samples=n_samples,
        seed=seed,
        contributions=contributions,
        ef_distributions=ef_dists,
        histogram={
            "bin_centers": [round(float((a + b) / 2), 2) for a, b in zip(edges[:-1], edges[1:])],
            "counts": [int(c) for c in counts],
        },
    )
