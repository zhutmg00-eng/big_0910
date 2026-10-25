"""碳价逐日补齐（2026-10-25）的数据质量守卫。"""
import pandas as pd

from src.config import RAW_DIR
from src.engine.carbon_price import load_carbon_price_data, price_window_stats

BACKFILL_START = "2026-06-10"


def _df():
    df = load_carbon_price_data()
    assert df is not None, "carbon_price_history.csv 缺失"
    return df


def test_backfilled_real_rows_cite_a_source():
    df = pd.read_csv(RAW_DIR / "carbon_price_history.csv", dtype=str, keep_default_na=False)
    recent = df[(df["日期"] >= BACKFILL_START) & (df["数据来源"] == "真实数据")]
    no_src = recent[(recent["来源链接"] == "") & (recent["日期"] != "2026-06-19")]
    assert no_src.empty, f"补齐区间内有真实数据行缺来源链接：{no_src['日期'].tolist()}"
    assert recent["来源链接"].str.startswith("http").sum() >= 80


def test_no_interpolated_rows_after_backfill_start():
    df = _df()
    late = df[(df["日期"] >= BACKFILL_START) & (df["数据来源"] != "真实数据")]
    assert late.empty, "补齐区间不应再有插值行"


def test_window_is_daily_and_covers_all_trading_days():
    w = price_window_stats(_df())
    # 近 90 个自然日内 65 个工作日，中秋 1 天 + 国庆 5 天休市
    assert w["n_obs"] >= 55, w
    assert w["basis"].startswith("近90个自然日")


def test_closes_are_plausible():
    df = _df()
    recent = df[df["日期"] >= BACKFILL_START]
    assert recent["收盘价"].between(60, 130).all()
    assert (recent["最高价"].fillna(recent["收盘价"]) >= recent["收盘价"]).all()
    assert (recent["最低价"].fillna(recent["收盘价"]) <= recent["收盘价"]).all()
