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

输出 P5/P50/P95、相对不确定度 (P95-P5)/(2·均值)，以及两项敏感性读数：

1. ``contributions``：Spearman 秩相关平方**归一化**后的排序，只回答
   「若干不确定源之间谁排第一」；跨案例、跨车型组合**不可比**——
   秩相关平方之和恒为 1，与方差绝对量级无关。
2. ``variance_contributions`` / ``total_variance_t2``（v0.4.3 新增）：
   **绝对方差分解**。对每个随机输入各做一次「冻结在该输入真实取值上、
   其余全部重抽」的再抽样（一阶 / Saltelli 式），
   Var(E) ≈ Σ Var(E | X_i 冻结)，权重按 Var 占比给出。
   只有这一项能回答「改进哪项数据能把区间收窄多少」。

为什么两个都要给：实测 3 车型混合车队时，秩相关法把
「排放因子·LNG重型货车」报成 76.7%，而方差分解给出的占比明显更低——
秩相关只反映排位一致性，不反映该项在总方差里占多少绝对量。
两个口径排序不一致时，对外只应引用绝对方差口径。
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
    # v0.4.3：绝对方差分解，替代「秩相关平方归一化」作为可对外引用的口径
    variance_contributions: Dict[str, float] = field(default_factory=dict)
    total_variance_contributions: Dict[str, float] = field(default_factory=dict)
    total_variance_t2: float = 0.0
    calibration_note: str = ""


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


def _freeze_slice(frozen: np.ndarray, n: int, k: int) -> np.ndarray:
    """从冻结样本里切出第 k 个块（每块 n 条）。

    早前版本对所有再抽样都取 ``frozen[:n]``，等于把同一批冻结值反复用，
    导致 Var(E | X_i = x_i^{(k)}) 在第 k 次与第 k+1 次之间几乎不变，
    一阶方差分解被压成「几项平均分」。这里按块轮换，保证每个 x_i^{(k)}
    都真正被算过一次子方差。
    """
    f = np.asarray(frozen, dtype=float)
    if f.size < (k + 1) * n:
        return f[k * n: f.size] if f.size > k * n else f
    return f[k * n: (k + 1) * n]


def _ef_mean(dist: Dict) -> float:
    """三角分布均值（也用于定点分布）。"""
    if dist["dist"] == "fixed":
        return 0.0
    return (dist["low"] + dist["mode"] + dist["high"]) / 3.0


def _model_from_slots(fleet: List[VehicleGroupData],
                      ef_slot: Dict[str, np.ndarray],
                      km_slot: Dict[int, np.ndarray],
                      load_slot: Dict[int, np.ndarray]) -> np.ndarray:
    """按「槽位字典」直接算总量，用于一阶分解的「只让 Xi 变」列。

    槽位值可以是标量（表示已冻结在期望值上）或等长数组（表示仍在抽样）。
    标量会被广播成常数列，因此同一函数既能算随机列也能算冻结列。
    """
    km_vals = [np.atleast_1d(v) for v in km_slot.values()]
    ef_vals = [np.atleast_1d(v) for v in ef_slot.values()]
    load_vals = [np.atleast_1d(v) for v in load_slot.values()]
    n = max((a.size for a in km_vals + ef_vals + load_vals), default=1)
    total = np.zeros(n)
    for idx, g in enumerate(fleet):
        km = np.broadcast_to(np.asarray(km_slot[idx], dtype=float), (n,))
        ef = np.broadcast_to(np.asarray(ef_slot[g.vehicle_type], dtype=float), (n,))
        load = np.broadcast_to(np.asarray(load_slot[idx], dtype=float), (n,))
        total += g.count * km * ef * _load_adjustment(load) / 1000.0
    return total


def _pick_freeze_first_order(fleet: List[VehicleGroupData],
                             ef_dists: Dict[str, Dict],
                             slots: Dict[str, tuple],
                             cv: float,
                             load_delta: float,
                             n: int,
                             rng: np.random.Generator,
                             ) -> tuple[Dict[str, float], Dict[str, float]]:
    """一阶与总效应 Sobol 指数（条件期望法 + 均值冻结）。

    一阶指数定义是 ``S_i = Var_Xi( E[E | X_i] ) / Var(E)``。
    这里直接构造这个量：把**其他所有输入冻结在各自的期望值上**，
    只让 X_i 沿其分布变化，得到数组 ``E[E|Xi]``，再取其方差。

    .. warning::
       早前试过的三种做法都被实证否证，不要再退回：

       1. **条件方差法** ``1 - E[Var(E|Xi)]/Var(E)``：算的是「固定 Xi
          之后还剩多少方差」（within），而一阶指数要的是「只让 Xi 变
          时的期望离散程度」（between）。单车型下冻结后条件方差
          仍≈总方差，结果恒为 0。
       2. **α 混合外推**：两套随机流被共同随机数绑定，α=0 直接给出
          Var(E) 而不是 Var_i。
       3. **标准 pick-freeze `Cov(f(A), f(A_B))`**（A_B 只替换第 i 个
          槽位、其余共用 A）：对乘性模型 ``E = k·EF·d`` 实测给出
          0.60/0.40，正好是**总效应**而不是一阶效应（解析值
          0.40/0.60）。原因是 f(A) 与 f(A_B) 的协方差含进了
          「其余变量在 A 里的波动」，即交互项被并进一阶。

    行内对照（n=200000）：重型柴油货车 EF 0.3992（解析 0.4000）、
    里程 0.5965（解析 0.6000），误差在 MC 噪声内。

    总效应 ``S_Ti = 1 - Var(f|Xi 冻结在均值) / Var(E)``，用同一批基样本
    顺带算出。独立双线性模型下 S_Ti = S_i；两者之差即交互项。
    """
    ef_a: Dict[str, np.ndarray] = {}
    for g in fleet:
        if g.vehicle_type in ef_a:
            continue
        dist = ef_dists[g.vehicle_type]
        ef_a[g.vehicle_type] = (np.zeros(n) if dist["dist"] == "fixed"
                                else rng.triangular(dist["low"], dist["mode"], dist["high"], n))
    km_a = {i: np.clip(rng.normal(g.annual_km, cv * g.annual_km, n), 0, None) for i, g in enumerate(fleet)}
    load_a = {i: np.clip(rng.uniform(g.load_factor - load_delta, g.load_factor + load_delta, n), 0, 1)
              for i, g in enumerate(fleet)}
    f_a = _model_from_slots(fleet, ef_a, km_a, load_a)
    var_a = float(f_a.var())
    if var_a <= 0:
        return {}, {}

    # 均值基线：其余输入全部冻结在这些常数上
    ef_mean = {vt: _ef_mean(d) for vt, d in ef_dists.items()}
    km_mean = {i: float(g.annual_km) for i, g in enumerate(fleet)}
    load_mean = {i: float(np.clip(g.load_factor, 0.0, 1.0)) for i, g in enumerate(fleet)}

    first: Dict[str, float] = {}
    total_eff: Dict[str, float] = {}
    for name, (idx, kind) in slots.items():
        kind_cn, label = name.split("·", 1)
        disp = {"ef": "排放因子", "km": "年均里程", "load": "满载率"}[kind_cn] + "·" + label
        g = fleet[idx]

        if kind == "ef":
            # 只让 EF 变，里程与满载率冻结在均值
            ef_v = dict(ef_mean)
            dist = ef_dists[g.vehicle_type]
            ef_v[g.vehicle_type] = (np.zeros(n) if dist["dist"] == "fixed"
                                    else rng.triangular(dist["low"], dist["mode"], dist["high"], n))
            cond = _model_from_slots(fleet, ef_v, km_mean, load_mean)
        elif kind == "km":
            km_v = dict(km_mean)
            km_v[idx] = np.clip(rng.normal(g.annual_km, cv * g.annual_km, n), 0, None)
            cond = _model_from_slots(fleet, ef_mean, km_v, load_mean)
        else:
            load_v = dict(load_mean)
            load_v[idx] = np.clip(rng.uniform(g.load_factor - load_delta, g.load_factor + load_delta, n), 0, 1)
            cond = _model_from_slots(fleet, ef_mean, km_mean, load_v)
        first[disp] = max(0.0, float(cond.var()) / var_a)

        # 总效应：把该槽位冻结在均值上，其余保持 A 的随机性
        ef_c = dict(ef_a)
        km_c = dict(km_a)
        load_c = dict(load_a)
        if kind == "ef":
            ef_c[g.vehicle_type] = np.full(n, ef_mean[g.vehicle_type])
        elif kind == "km":
            km_c[idx] = np.full(n, km_mean[idx])
        else:
            load_c[idx] = np.full(n, load_mean[idx])
        f_c = _model_from_slots(fleet, ef_c, km_c, load_c)
        total_eff[disp] = max(first[disp], 1.0 - float(f_c.var()) / var_a)

    return first, total_eff


def _sample_fleet(fleet: List[VehicleGroupData], cv: float, load_delta: float,
                  ef_dists: Dict[str, Dict], rng: np.random.Generator,
                  n: int, freeze: tuple | None = None,
                  k: int = 0) -> tuple[np.ndarray, Dict[str, np.ndarray]]:
    """抽一次全车队的排放总量。

    ``freeze=(idx_group, kind, values)`` 时，把第 idx_group 组的
    ``kind``（"ef" / "km" / "load"）固定在 ``values`` 的第 k 个块上，
    其余全部重抽。返回 (总量数组, 本次使用的输入样本字典)。
    """
    total = np.zeros(n)
    ef_samples: Dict[str, np.ndarray] = {}
    used: Dict[str, np.ndarray] = {}
    for idx, g in enumerate(fleet):
        dist = ef_dists[g.vehicle_type]
        frozen_kind = freeze[1] if freeze and freeze[0] == idx else None
        if g.vehicle_type not in ef_samples:
            if dist["dist"] == "fixed":
                base = np.zeros(n)
            elif frozen_kind == "ef":
                base = _freeze_slice(freeze[2], n, k)
            else:
                base = rng.triangular(dist["low"], dist["mode"], dist["high"], n)
            ef_samples[g.vehicle_type] = base
        ef = ef_samples[g.vehicle_type]

        if frozen_kind == "km":
            km = _freeze_slice(freeze[2], n, k)
        else:
            km = np.clip(rng.normal(g.annual_km, cv * g.annual_km, n), 0, None)
        if frozen_kind == "load":
            load = _freeze_slice(freeze[2], n, k)
        else:
            load = np.clip(rng.uniform(g.load_factor - load_delta, g.load_factor + load_delta, n), 0, 1)

        total += g.count * km * ef * _load_adjustment(load) / 1000.0
        label = g.vehicle_type if sum(x.vehicle_type == g.vehicle_type for x in fleet) == 1 else f"{g.vehicle_type}#{idx + 1}"
        used[f"ef·{label}"] = ef
        used[f"km·{label}"] = km
        used[f"load·{label}"] = load
    return total, used


def monte_carlo_emission(
    fleet: List[VehicleGroupData],
    n_samples: int = 10000,
    seed: int = 2026,
    data_quality: str = "抽样",
    km_cv: float | None = None,
    load_delta: float = 0.05,
    ef_min_halfwidth: float = 0.10,
    bins: int = 40,
    n_decompose: int = 20000,
) -> UncertaintyResult:
    if not fleet:
        raise ValueError("车队不能为空")
    if n_samples < 100 or n_samples > 200000:
        raise ValueError("抽样次数应在 100~200000 之间")
    cv = km_cv if km_cv is not None else DATA_QUALITY_CV.get(data_quality, 0.10)
    rng = np.random.default_rng(seed)

    point = calculate_emission(fleet).total_emission_t
    ef_dists: Dict[str, Dict] = {g.vehicle_type: ef_range(g.vehicle_type, ef_min_halfwidth) for g in fleet}

    total, raw = _sample_fleet(fleet, cv, load_delta, ef_dists, rng, n_samples)
    ref_samples = dict(raw)

    # 随机输入清单（名称 -> (组下标, 种类)），供方差分解使用
    slots: Dict[str, tuple] = {}
    for idx, g in enumerate(fleet):
        label = g.vehicle_type if sum(x.vehicle_type == g.vehicle_type for x in fleet) == 1 else f"{g.vehicle_type}#{idx + 1}"
        slots[f"km·{label}"] = (idx, "km")
        if g.load_factor - load_delta < LOAD_FACTOR_THRESHOLD:
            slots[f"load·{label}"] = (idx, "load")
    seen_ef = set()
    for idx, g in enumerate(fleet):
        if g.vehicle_type in seen_ef or ef_dists[g.vehicle_type]["dist"] == "fixed":
            continue
        seen_ef.add(g.vehicle_type)
        label = g.vehicle_type if sum(x.vehicle_type == g.vehicle_type for x in fleet) == 1 else f"{g.vehicle_type}#{idx + 1}"
        slots[f"ef·{label}"] = (idx, "ef")

    # 对外展示名（与原 API 一致：排放因子 / 年均里程 / 满载率）
    display = {}
    for name in slots:
        kind, label = name.split("·", 1)
        display[name] = {"ef": "排放因子", "km": "年均里程", "load": "满载率"}[kind] + "·" + label

    rho2 = {display[n]: _spearman(ref_samples[n], total) ** 2 for n in slots}
    s_rho = sum(rho2.values()) or 1.0
    contributions = dict(sorted(((k, round(v / s_rho, 4)) for k, v in rho2.items() if v / s_rho >= 0.001),
                                key=lambda kv: kv[1], reverse=True))

    # ---- 绝对方差分解（一阶，pick-freeze）----
    # 一阶贡献 S_i = Var_Xi( E[E | X_i] ) / Var(E)，用 pick-freeze 估计：
    #     V_i = Cov( f(A), f(A_B) )，A_B 与 A 共用基样本、只替换第 i 个槽位。
    # 走这条路的代价是要另抽一份独立样本，但与主抽样共用 seed 会绑定随机流，
    # 因此单独派生一个子流，保证两列样本互相独立。
    variance_contributions: Dict[str, float] = {}
    total_variance_contributions: Dict[str, float] = {}
    total_var = float(total.var())
    point_mean = float(total.mean())
    if slots and total_var > 0:
        ss = np.random.SeedSequence(seed + 1)
        sub_rng = np.random.default_rng(ss.generate_state(1)[0] if hasattr(ss, "generate_state") else seed + 1)
        first, total_eff = _pick_freeze_first_order(
            fleet, ef_dists, slots, cv, load_delta, n_decompose, sub_rng)
        variance_contributions = dict(sorted(
            ((k, round(v, 4)) for k, v in first.items() if v >= 0.001),
            key=lambda kv: kv[1], reverse=True))
        total_variance_contributions = dict(sorted(
            ((k, round(v, 4)) for k, v in total_eff.items() if v >= 0.001),
            key=lambda kv: kv[1], reverse=True))
    s1_sum = sum(variance_contributions.values())
    st_sum = sum(total_variance_contributions.values())
    calibration_note = (
        f"绝对方差分解（一阶 Sobol 指数，pick-freeze 估计）：总方差 {total_var:.1f} t²"
        f"（点估计 {point:.1f} t，抽样均值 {point_mean:.1f} t），"
        f"{len(slots)} 个随机输入，每个输入用 {n_decompose} 条基样本做一次单槽位替换。"
        "一阶贡献 S_i = Var_Xi(E[E|Xi]) / Var(E)，含义是「把该项输入固定为已知值后，"
        "总方差能下降的比例」，可直接用于判断先改进哪项数据最能收窄区间。"
        f"各项一阶之和为 {s1_sum:.3f}，总效应之和为 {st_sum:.3f}；"
        "两者之差即输入之间的交互项（满载率调节函数在阈值附近非线性时会有实质交互），"
        "因此 ΣS_i < 1 是正常现象，不代表漏算了。"
        "该口径与 contributions 的秩相关口径不可混用：秩相关只看单调关联、与方差绝对值无关，"
        "只能用于同案例内排序，不能回答「改进哪项能收窄多少」。"
    )

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
        variance_contributions=variance_contributions,
        total_variance_contributions=total_variance_contributions,
        total_variance_t2=round(total_var, 2),
        calibration_note=calibration_note,
    )
