"""小样本无台账误差包络必须与引擎口径一致，且不得被当成准确率验证。

背景（2026-10-27，I-5）：
`docs/known_gaps.md` GAP-4 自陈验证集是「有台账的头部企业」，目标用户是
「无台账的中小车队」。补 `scripts/small_fleet_envelope.py` 后，最容易犯的
错误有两类，本文件各拦一条：

1. **把包络当准确率**：脚本里的「真值」是同一引擎按一组不可观测参数算出的，
   误差只来自输入猜测偏差。若材料把它写成「无台账场景下准确率 ±X%」，
   就是把输入不确定性冒充分数验证。
2. **数字与引擎脱钩**：包络、单因素分解、误差预算都依赖
   `calculate_load_adjustment` 的具体形状（阈值 0.75、α=0.15）。引擎参数
   一改而报告未重算，读者会引用一组失效的界。这里用引擎复算并比对。

不测「数值恰好等于多少」——那会随画像设计变化，属于把预期值抄一遍。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "small_fleet_envelope.py"
RESULT = ROOT / "data" / "processed" / "small_fleet_envelope.json"
REPORT = ROOT / "docs" / "small_fleet_envelope.md"


def _module():
    import importlib.util

    spec = importlib.util.spec_from_file_location("small_fleet_envelope", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _payload() -> dict:
    """结果 JSON 是运行时产物（`data/processed/` 被 gitignore）。

    因此不能只靠读文件：全新 clone 或 CI 上没有这个文件时，测试会整片
    skip，守卫等于没有。缺文件时直接用模块现算一份——4 个画像 × 35 组合，
    百毫秒量级，比让守卫失效划算。
    """
    if RESULT.exists():
        return json.loads(RESULT.read_text(encoding="utf-8"))
    return _module().analyse_all()


def test_result_and_report_exist() -> None:
    """报告是入库产物，必须存在；结果 JSON 是运行时产物，只在你跑过脚本时存在。"""
    assert REPORT.exists(), "未生成报告（docs/small_fleet_envelope.md 应入库）"
    assert _payload()["profiles"], "无法取得包络数据"


def test_declares_it_is_not_accuracy_validation() -> None:
    """结果与报告都必须自陈「不是准确率验证」。"""
    note = _payload()["note"]
    assert "不是准确率验证" in note
    assert "不可互换引用" in note

    report = REPORT.read_text(encoding="utf-8")
    assert "这不是准确率验证" in report, "报告缺少免责声明，会被当成验证结果引用"
    assert "不能与 4.23%" in report, "报告未说明与有台账 MAPE 4.23% 的区别"


def test_report_does_not_quote_percentiles() -> None:
    """禁掉分位数/命中率作为结论：对称网格上算这些只是网格构造的产物。

    允许在「不报中位数或命中率」这类否定句里出现——那是方法说明，
    恰恰应该保留。
    """
    report = REPORT.read_text(encoding="utf-8")
    for banned in ("误差中位", "平均绝对误差", "±10% 内占比", "命中率"):
        for line in report.splitlines():
            if banned not in line:
                continue
            assert any(neg in line for neg in ("不报", "没有意义", "不测", "不用")), (
                f"报告把「{banned}」当结论用了：{line.strip()[:120]}"
            )


def test_envelope_matches_engine_recomputation() -> None:
    """用引擎原样复算每个画像的包络极值，必须与 JSON 一致。"""
    mod = _module()
    for row, profile in zip(_payload()["profiles"], mod.SMALL_FLEET_PROFILES, strict=True):
        true_value = mod._emission(profile["mix"], profile["true_km"], profile["true_load"])
        errors = [
            (mod._scaled(profile, km, lf) - true_value) / true_value * 100
            for km in mod.KM_ERRORS
            for lf in mod.LOAD_ERRORS
        ]
        assert row["envelope_pct"]["min"] == pytest.approx(round(min(errors), 2), abs=0.02)
        assert row["envelope_pct"]["max"] == pytest.approx(round(max(errors), 2), abs=0.02)


def test_km_effect_is_exactly_linear() -> None:
    """里程是线性因子：仅改里程时，偏差必须精确等于里程偏差。"""
    mod = _module()
    for profile in mod.SMALL_FLEET_PROFILES:
        true_value = mod._emission(profile["mix"], profile["true_km"], profile["true_load"])
        for km_err in mod.KM_ERRORS:
            est = mod._scaled(profile, km_err, 0.0)
            got = (est - true_value) / true_value * 100
            assert got == pytest.approx(km_err * 100, abs=0.05), (
                f"{profile['name']} 里程偏差 {km_err:+.0%} 时输出偏差 {got:+.2f}%，"
                "说明引擎里出现了额外的非线性项"
            )


def test_load_effect_stays_within_analytic_cap() -> None:
    """满载率单独效应受 LF 值域约束，不可能超过 +11.25% / −10.1%。"""
    mod = _module()
    upper = (1 + mod.LF_DESIGN_CAP - 1) * 100                 # +11.25%
    lower = (1 / (1 + mod.LF_DESIGN_CAP) - 1) * 100           # −10.1%
    for row in _payload()["profiles"]:
        load_only = row["decomposition_pct"]["load_only_max_abs"]
        assert load_only <= max(upper, -lower) + 0.05, (
            f"{row['profile']} 的满载率单独效应 {load_only}% 超出 LF 值域上界，"
            "说明 LF 公式或阈值被改动而分析未同步"
        )


def test_km_dominates_every_profile() -> None:
    """里程效应必须大于满载率效应，否则「先补里程」的建议不成立。"""
    for row in _payload()["profiles"]:
        dec = row["decomposition_pct"]
        assert dec["km_only_max_abs"] > dec["load_only_max_abs"], (
            f"{row['profile']} 上满载率效应不小于里程效应，部署建议需要改写"
        )


def test_km_budget_is_verified_by_engine() -> None:
    """「里程需猜准到 ±X%」必须真的成立：该偏差下所有满载率猜测都在 ±10% 内。"""
    mod = _module()
    for row, profile in zip(_payload()["profiles"], mod.SMALL_FLEET_PROFILES, strict=True):
        budget = row["km_budget_for_10pct"]
        assert budget > 0, f"{row['profile']} 未给出可用里程预算"
        true_value = mod._emission(profile["mix"], profile["true_km"], profile["true_load"])
        worst = max(
            abs((mod._scaled(profile, budget, lf) - true_value) / true_value * 100)
            for lf in mod.LOAD_ERRORS
        )
        assert worst <= 10.0 + 0.05, (
            f"{row['profile']} 声称里程 ±{budget:.0%} 可保证 ±10%，"
            f"实测最坏 {worst:.2f}%"
        )


def test_profiles_are_small_fleets() -> None:
    """画像必须真的是「中小车队」：10–50 辆。"""
    for row in _payload()["profiles"]:
        assert 10 <= row["vehicles"] <= 50, (
            f"{row['profile']} 有 {row['vehicles']} 辆，与 GAP-4 声明的目标用户不符"
        )


def test_all_vehicle_types_resolve() -> None:
    """画像里的车型必须都在因子表里，否则真实排放会被静默算错。"""
    from src.engine.emission_factors import get_emission_factor

    mod = _module()
    for profile in mod.SMALL_FLEET_PROFILES:
        for vtype, _ in profile["mix"]:
            assert get_emission_factor(vtype) is not None, f"因子表缺车型 {vtype}"
