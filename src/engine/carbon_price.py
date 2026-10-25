"""碳价参考与模拟碳预算情景成本估算。

成本计算公式：
    Cost = max(Gap, 0) × P_current
    成本区间: [Gap × P_min(90d), Gap × P_max(90d)]
    90d 窗口统一由 price_window_stats() 计算（近 90 个自然日、仅真实成交点）。
"""
try:
    import pandas as pd
except ImportError:
    pd = None
from typing import Any


def load_carbon_price_data(csv_path: str = None) -> Any:
    """
    加载碳价历史数据

    Args:
        csv_path: CSV文件路径。如果未提供，尝试默认路径。

    Returns:
        DataFrame或None（文件不存在或pandas未安装时）
    """
    if pd is None:
        return None
    from src.config import RAW_DIR
    path = csv_path or str(RAW_DIR / "carbon_price_history.csv")

    try:
        df = pd.read_csv(path, parse_dates=["日期"])
        df = df.sort_values("日期")
        return df
    except Exception:
        return None


def carbon_price_data_available(csv_path: str = None) -> bool:
    """碳价原始数据是否可用（供 UI/API 区分“真实统计”与“模拟参考价”）。"""
    return load_carbon_price_data(csv_path) is not None


WINDOW_DAYS = 90


def price_window_stats(df, days: int = WINDOW_DAYS, real_only: bool = True) -> dict:
    """碳价窗口统计——全项目唯一口径（UI、API、情景成本、derived_metrics 都调用它）。

    口径说明（v0.4.1 统一）：
    - 窗口 = 序列最后一个日期往前 ``days`` 个**自然日**；
    - 默认只用 ``数据来源 == 真实数据`` 的观测点。原始序列早期为周频且大量插值（2026-10-25 起，2026-06-10 后已补齐逐日真实成交），
      若按“末 90 行”取窗，实际覆盖约 90 周（1.7 年），会把 2024—2025 年的低价混入，
      这正是旧版 78.67 与 90.72 两个“近90日均价”打架的根源；
    - 返回观测点数 ``n_obs``，样本少时由前端提示“仅 n 个真实成交点”。
    - ``current`` 与 mean/min/max 同源于窗口内观测点，不取全序列末行：末行可能是插值，
      若混用会出现“参考价落在区间之外”的自相矛盾（该页明确声明插值不参与统计）。
    """
    if df is None or df.empty:
        return {}
    data = df
    if real_only and "数据来源" in df.columns:
        real = df[df["数据来源"] == "真实数据"]
        if not real.empty:
            data = real
    cutoff = df["日期"].max() - pd.Timedelta(days=days)
    win = data[data["日期"] >= cutoff]
    if win.empty:
        win = data.tail(1)
    prices = win["收盘价"]
    return {
        # 与 mean/min/max 同源：窗口内最后一个观测点，避免与区间口径打架
        "current": round(float(prices.iloc[-1]), 2),
        "mean": round(float(prices.mean()), 2),
        "max": round(float(prices.max()), 2),
        "min": round(float(prices.min()), 2),
        # 观测点间隔不规则，只给价格水平的变异系数，不再伪装成“日波动率”
        "cv_pct": round(float(prices.std(ddof=1) / prices.mean() * 100), 2) if len(prices) > 1 else 0.0,
        "n_obs": int(len(win)),
        "window_start": str(win["日期"].min().date()),
        "window_end": str(win["日期"].max().date()),
        "basis": f"近{days}个自然日·{'仅真实成交' if real_only else '含插值'}",
    }


def calculate_price_stats(df) -> dict:
    """碳价统计指标（中文键，供 UI 与报告使用）。"""
    w = price_window_stats(df)
    if not w:
        return {}
    return {
        "当前价": w["current"],
        "近90日均价": w["mean"],
        "近90日最高": w["max"],
        "近90日最低": w["min"],
        "价格离散度CV(%)": w["cv_pct"],
        "观测点数": w["n_obs"],
        "统计口径": w["basis"],
    }


def estimate_compliance_cost(gap_t: float, price_df=None) -> dict:
    """
    基于历史碳价估算模拟预算差额的情景成本或潜在价值。

    函数名为兼容现有调用保留；结果不代表物流企业的法定履约成本、
    可交易配额或确定收益。

    Args:
        gap_t: 模拟碳预算差额 (tCO2e)，正数为超出预算
        price_df: 碳价历史数据DataFrame。如果None，使用模拟数据。

    Returns:
        dict: 成本估算结果
    """
    # 如果没有真实数据，使用模拟参考价。回退必须在返回结果里显式标注，
    # 否则接口输出的数字与真实统计无法区分（会被当作实测结论引用）。
    is_fallback = price_df is None or (pd is not None and price_df.empty)
    if is_fallback:
        # 模拟参考价（基于2024-2025年全国碳市场大致区间）
        current_price = 70.0  # 元/吨
        avg_price = 68.0
        min_price = 55.0
        max_price = 85.0
        volatility = 8.5
        data_source = "模拟参考价（碳价原始数据不可用，非实测统计）"
    else:
        w = price_window_stats(price_df)
        current_price, avg_price = w["current"], w["mean"]
        min_price, max_price, volatility = w["min"], w["max"], w["cv_pct"]
        data_source = f"{w['basis']}（{w['window_start']}—{w['window_end']}，{w['n_obs']} 个观测点）"

    if gap_t <= 0:
        judgement = "基本平衡" if abs(gap_t) < 1e-9 else "低于模拟碳预算"
        return {
            "情景判断": judgement,
            "预算结余_t": round(abs(gap_t), 2),
            "潜在价值_low": round(abs(gap_t) * min_price, 2),
            "潜在价值_high": round(abs(gap_t) * max_price, 2),
            "参考碳价_元每吨": current_price,
            "碳价数据来源": data_source,
            "is_fallback_price": is_fallback,
            "备注": "仅按全国碳市场价格估算潜在价值，不代表可交易配额或实际收益",
        }

    return {
        "情景判断": "超出模拟碳预算",
        "预算差额_t": round(gap_t, 2),
        "当前碳价_元每吨": current_price,
        "近90日均价_元每吨": avg_price,
        "碳价离散度CV": f"{volatility}%",
        "情景成本_参考价": round(gap_t * current_price, 2),
        "情景成本区间_low": round(gap_t * min_price, 2),
        "情景成本区间_high": round(gap_t * max_price, 2),
        "碳价数据来源": data_source,
        "is_fallback_price": is_fallback,
        "备注": "科研情景估算，不代表物流企业当前存在碳市场履约义务",
    }
