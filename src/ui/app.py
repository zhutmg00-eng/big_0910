"""Streamlit application entry point."""

import streamlit as st

from src.ui.views.advisory import render_policy_advisor, render_report
from src.ui.views.overview import render_factors, render_home, render_inventory
from src.ui.views.reduction import render_reduction
from src.ui.views.validation import render_validation
from src.ui.theme import apply_theme, render_brand


st.set_page_config(
    page_title="碳路 · 物流碳决策工作台",
    page_icon="C",
    layout="wide",
    initial_sidebar_state="expanded",
)

apply_theme()
render_brand()

PAGES = {
    "工作台": render_home,
    "排放盘点": render_inventory,
    "减排分析": render_reduction,
    "政策顾问": render_policy_advisor,
    "排放因子": render_factors,
    "方法与验证": render_validation,
    "报告导出": render_report,
}

with st.sidebar:
    st.markdown(
        """
        <div class="sidebar-brand" aria-label="碳路物流碳决策工作台">
            <span class="sidebar-brand__mark" aria-hidden="true">C</span>
            <span><strong>碳路</strong><small>科研决策原型</small></span>
        </div>
        """,
        unsafe_allow_html=True,
    )
    page = st.radio(
        "主导航",
        list(PAGES),
        key="current_page",
        label_visibility="collapsed",
    )
    st.markdown(
        """
        <div class="sidebar-note">
            <strong>核算边界</strong>
            <span>当前核算车辆直接运营排放。新能源车购电间接排放及全生命周期排放未纳入。</span>
        </div>
        """,
        unsafe_allow_html=True,
    )

PAGES[page]()
