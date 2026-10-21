"""减排情景排序与候选筛选。

锁定「最优方案」的语义：系统给出的推荐必须是净节省额最大的方案，
不能因为减排量小、比值大就被排在前面。
"""
from __future__ import annotations

from src.engine.calculator import VehicleGroupData
from src.engine.reduction import analyze_reduction_scenario, find_optimal_reduction


FLEET_MIXED = [
    VehicleGroupData("重型柴油货车", 10, 80000, 0.85),
    VehicleGroupData("轻型柴油货车", 1, 10000, 0.5),
]
FLEET_HEAVY = [VehicleGroupData("重型柴油货车", 50, 80000, 0.85)]


def test_recommendation_is_not_a_near_zero_reduction():
    """满载率微调只减排 0.02%，不能因「性价比」比值大而成为推荐方案。"""
    result = find_optimal_reduction(FLEET_MIXED)
    assert result.scenarios, "应至少返回一个候选方案"
    best = result.scenarios[0]
    assert best.reduction_pct >= 0.05, (
        f"推荐方案减排比例仅 {best.reduction_pct:.4f}%，属于无实质减排"
    )


def test_recommendation_matches_max_net_saving():
    """推荐方案的净节省额应为全部候选中的最大值。"""
    result = find_optimal_reduction(FLEET_MIXED)
    best = result.scenarios[0]
    best_saving = best.cost_savings.get("节省_元") or 0.0

    # 逐个单措施复算，确认没有更高节省额的方案被漏掉
    candidates = {
        "替换全部重卡为新能源": {"替换为新能源物流车": 10},
        "全部重卡换 LNG": {"重型货车更换LNG": 10},
    }
    for label, changes in candidates.items():
        single = analyze_reduction_scenario(FLEET_MIXED, changes)
        saving = single.cost_savings.get("节省_元") or 0.0
        assert best_saving >= saving - 1e-6, (
            f"推荐方案节省 {best_saving:.2f} 元，低于「{label}」的 {saving:.2f} 元"
        )


def test_replacement_beats_partial_combination_for_pure_fleet():
    """单一柴油车队应推荐全量替换，而不是减排更少的局部组合。"""
    result = find_optimal_reduction(FLEET_HEAVY)
    best = result.scenarios[0]
    assert "替换为新能源" in best.name, f"预期全量替换方案，实际推荐：{best.name}"
    assert best.reduction_pct > 90, f"全量替换应减排 90% 以上，实际 {best.reduction_pct:.2f}%"


def test_ranking_basis_reported_when_no_budget_overrun():
    """无可比节省额时必须说明排序依据，不能让读者以为在按性价比排序。"""
    result = find_optimal_reduction(FLEET_HEAVY)
    notes = " ".join(result.recommendations)
    has_explicit_basis = ("节省额" in notes) or ("减排量" in notes)
    assert has_explicit_basis, "推荐说明未交代排序依据"


def test_budget_mode_labels_candidate_not_optimal():
    """给出预算时不能把结果称作「最优方案」，因为预算未真正参与筛选。"""
    result = find_optimal_reduction(FLEET_MIXED, budget=1_000_000)
    assert result.scenarios
    name = result.scenarios[0].name
    assert "最优方案" not in name, f"预算模式下不应自称最优方案：{name}"


def test_gap_elimination_message_shows_scenario_own_reduction():
    """每个情景的"可消除超出量"文本必须带上它自己的减排量。

    旧实现打印的是基线超出量（所有情景共用常数），于是减排 350.8 t 与
    2104.8 t 的两个情景都会写成"可消除模拟碳预算超出量（210.5 tCO2e）"，
    读者无从判断两者差别有多大。
    """
    from src.engine.reduction import ReductionScenario, compare_scenarios

    fleet = [VehicleGroupData("重型柴油货车", 30, 80000, 0.85)]
    scenarios = [
        ReductionScenario(name=f"替换{k}辆", description="", changes={"替换为新能源物流车": k})
        for k in (5, 30)
    ]
    comparison = compare_scenarios(fleet, scenarios)

    gap_lines = [n for n in comparison.recommendations if "消除模拟碳预算超出量" in n]
    assert len(gap_lines) == 2, f"预期两个情景各有一条说明，实际 {gap_lines}"

    reductions = sorted(
        s.reduction_t for s in comparison.scenarios if s.reduction_t > 0
    )
    for line in gap_lines:
        # 文本里必须出现该情景自己的减排量（两位以内可差一位小数）
        assert any(f"{r:.1f}" in line for r in reductions), (
            f"超出量说明未包含该情景的减排量：{line}"
        )


def _render_reduction_app(load_factor: float):
    """用 AppTest 渲染减排页，返回 AppTest 实例（不发真实请求）。"""
    from streamlit.testing.v1 import AppTest

    script = """
import streamlit as st
from src.ui.views.reduction import render_reduction

st.session_state["company_name"] = "示例"
st.session_state["fleet_data"] = [{"vehicle_type": "重型柴油货车", "count": 10,
                                  "annual_km": 100000, "load_factor": %r}]
st.session_state["carbon_result"] = {
    "company_name": "示例",
    "total_emission_t": 2730.0,
    "total_vehicles": 10,
    "emission_by_type": {"重型柴油货车": {"车辆数": 10, "排放量_t": 2730.0}},
    "carbon_budget": {"预算_t": 2800.0, "预算差额_t": -70.0, "状态": "低于预算"},
    "scenario_cost": {},
    "methodology_note": "",
}
render_reduction()
""" % (load_factor,)
    at = AppTest.from_string(script, default_timeout=120).run()
    assert not at.exception, at.exception[0].value if at.exception else ""
    return at


class TestReductionUiHasNoInteractionDeadlock:
    """第 8 轮评审实测：满载率 98% 时「目标满载率」滑块永远无效、按钮却能点。

    根因是滑块 ``value=max(当前, 0.80)`` 且 ``max=100``——当前满载率已经
    98% 时目标值不可能高于当前值，点下去只会得到「请提高目标满载率」。
    """

    def test_full_load_hides_target_slider(self):
        at = _render_reduction_app(1.0)
        labels = [slider.label for slider in at.slider]
        assert "目标满载率" not in labels
        hints = " ".join(getattr(item, "value", "") or "" for item in at.info)
        assert "没有空间" in hints

    def test_full_load_disables_submit(self):
        at = _render_reduction_app(1.0)
        submit = [b for b in at.button if b.label == "计算减排情景"]
        assert submit and submit[0].disabled

    def test_normal_load_keeps_slider_available(self):
        at = _render_reduction_app(0.60)
        labels = [slider.label for slider in at.slider]
        assert "目标满载率" in labels


class TestEconomicParametersAreEditable:
    """第 8 轮评审 P0-3：界面里没有任何油价/电价/折现率入口。

    评审实测：全部参数吃 src/engine/tco.py 的硬编码默认值，电价 2.0 +
    油价 5.0 时回收期变 None（永不回本），而用户既看不到假设也改不了。
    「你按什么价算的」是评委与老板必问的第一个问题。
    """

    _SCRIPT = """
import streamlit as st
from src.ui.views.reduction import _calculate_reduction, _render_econ_sanity_hint

st.session_state["company_name"] = "示例"
fleet = [{"vehicle_type": "重型柴油货车", "count": 10, "annual_km": 100000, "load_factor": 0.60}]
carbon = {"carbon_budget": {"情景减排目标": 0.0}}
_render_econ_sanity_hint(DIESEL, ELEC)
_calculate_reduction(carbon, fleet, "重型柴油货车", 10, 0, 0.60,
                     diesel_price=DIESEL, elec_price=ELEC,
                     discount_rate_pct=6.0, lifespan_years=5)
st.write(st.session_state["reduction_result"]["tco_analysis"]["overall_payback_period_years"])
"""

    def _run(self, diesel: float, elec: float):
        from streamlit.testing.v1 import AppTest

        script = self._SCRIPT.replace("DIESEL", str(diesel)).replace("ELEC", str(elec))
        at = AppTest.from_string(script, default_timeout=120).run()
        assert not at.exception, at.exception[0].value if at.exception else ""
        return at

    @staticmethod
    def _payback(at) -> str:
        # st.write 会把 Python 值渲染成 Markdown 代码块（``2.34``），需剥反引号
        return str(at.markdown[-1].value).strip("`")

    def test_electricity_price_changes_payback(self):
        cheap = self._payback(self._run(7.50, 0.80))
        expensive = self._payback(self._run(7.50, 1.80))
        assert cheap != expensive
        assert float(cheap) < 5.0
        assert float(expensive) > 100.0

    def test_inverted_prices_give_no_payback(self):
        at = self._run(5.00, 2.00)
        assert self._payback(at) == "None"
        warnings = " ".join(str(w.value) for w in at.warning)
        assert "没有节省" in warnings or "不回本" in warnings

    def test_hint_shows_energy_cost_gap(self):
        at = self._run(7.50, 0.80)
        captions = " ".join(str(c.value) for c in at.caption)
        assert "元" in captions and "能源成本下降" in captions
