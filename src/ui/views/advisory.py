"""Policy-advisor and report-export views."""

from __future__ import annotations

from pathlib import Path

import requests
import streamlit as st

from src.ui.api_client import API_BASE_URL, api_post, show_api_error
from src.ui.navigation import navigate_to
from src.ui.theme import empty_state, notice, page_header


RETRIEVER_LABELS = {"bm25": "BM25", "vector": "语义向量", "keyword": "字面规则", "rerank": "精排"}


def _render_sources(
    sources: list,
    latency_ms: float | None = None,
    evidence_warning: str = "",
) -> None:
    """展示可溯源的证据段落：来源文件、分块 ID、命中检索器与原文摘录。

    证据为空时必须显式告警而不是静默隐藏溯源区——空证据 + 正常回答
    意味着回答没有任何政策条款支撑，用户看不到溯源区会误以为已核验。
    """
    if not sources:
        st.warning(
            evidence_warning
            or "本次未检索到任何政策证据，回答不含可溯源条款，请勿作为政策依据引用。"
        )
        return
    title = f"证据溯源 · {len(sources)} 条" + (f" · {latency_ms:.0f} ms" if latency_ms else "")
    with st.expander(title):
        for i, src in enumerate(sources, 1):
            tags = " · ".join(RETRIEVER_LABELS.get(r, r) for r in src.get("retrievers", []))
            rel = src.get("relevance")
            st.markdown(
                f"**[{i}] {src.get('source', '未知来源')}**"
                + (f"（{src['date']}）" if src.get("date") else "")
                + (f"  \n`{src.get('chunk_id', '')}`" if src.get("chunk_id") else "")
                + (f" · 命中：{tags}" if tags else "")
                + (f" · 相关度 {rel:.2f}" if isinstance(rel, (int, float)) else "")
            )
            if src.get("excerpt"):
                st.caption(src["excerpt"])


def _render_message(message: dict) -> None:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        _render_sources(
            message.get("sources", []),
            message.get("latency_ms"),
            message.get("evidence_warning", ""),
        )


def render_policy_advisor() -> None:
    page_header(
        "资料检索",
        "交通低碳政策顾问",
        "围绕交通低碳、排放核算和碳市场资料提问，并保留回答所引用的政策来源。",
    )
    st.session_state.setdefault("messages", [])

    if not st.session_state.messages:
        empty_state(
            "还没有检索记录",
            "可以从核算边界、运输行业政策或排放因子依据开始提问。回答用于资料梳理，不替代正式合规意见。",
        )
        q1, q2 = st.columns(2)
        sample_one = q1.button("物流企业是否纳入全国碳市场？", width="stretch")
        sample_two = q2.button("运输排放盘查需要哪些活动数据？", width="stretch")
    else:
        sample_one = sample_two = False

    for message in st.session_state.messages:
        _render_message(message)

    typed_prompt = st.chat_input("输入交通低碳或排放核算问题")
    prompt = (
        "物流运输企业目前是否纳入全国碳市场？请说明适用边界。"
        if sample_one
        else "运输排放盘查通常需要收集哪些活动数据？"
        if sample_two
        else typed_prompt
    )
    if not prompt:
        return

    user_message = {"role": "user", "content": prompt}
    st.session_state.messages.append(user_message)
    _render_message(user_message)

    with st.chat_message("assistant"):
        with st.spinner("正在检索政策资料…"):
            try:
                response = api_post(
                    "/api/ask",
                    {
                        "question": prompt,
                        "carbon_profile": st.session_state.get("carbon_result", {}),
                    },
                )
                if response.status_code != 200:
                    show_api_error(response)
                    return
                result = response.json()
                answer = result.get("answer", "未检索到可用回答。")
                sources = result.get("retrieved_sources", [])
                evidence_warning = result.get("evidence_warning", "")
                st.markdown(answer)
                _render_sources(sources, result.get("latency_ms"), evidence_warning)
                st.session_state.messages.append(
                    {"role": "assistant", "content": answer, "sources": sources,
                     "evidence_warning": evidence_warning,
                     "latency_ms": result.get("latency_ms")}
                )
            except requests.RequestException as exc:
                st.error(f"无法连接政策检索服务（{API_BASE_URL}）：{exc}")


def render_report() -> None:
    page_header(
        "成果整理",
        "情景报告导出",
        "将最近一次排放核算、碳预算情景和政策顾问建议整理为 PDF 报告。",
    )
    result = st.session_state.get("carbon_result")
    if not result:
        empty_state("暂无可导出的核算结果", "先完成排放盘点，系统才会生成报告所需的基线和情景数据。")
        st.button(
            "前往排放盘点",
            type="primary",
            on_click=navigate_to,
            args=("排放盘点",),
        )
        return

    budget = result.get("carbon_budget", {})
    m1, m2, m3 = st.columns(3)
    m1.metric("企业", st.session_state.get("company_name", result.get("company_name", "未命名企业")))
    m2.metric("直接运营排放", f"{result.get('total_emission_t', 0):,.0f} tCO2e")
    m3.metric("预算差额", f"{budget.get('预算差额_t', 0):+,.0f} tCO2e")

    st.markdown("## 报告将包含")
    report_sections = [
        {"章节": "核算摘要", "内容": "车队规模、直接运营排放和核算边界"},
        {"章节": "分车型明细", "内容": "车型活动水平与排放结果"},
        {"章节": "情景判断", "内容": "模拟碳预算差额与碳价对标成本"},
        {"章节": "资料建议", "内容": "最近一次政策顾问回答（如有）"},
    ]
    st.table(report_sections)

    if st.button("生成最新 PDF", type="primary", width="stretch"):
        _generate_report(result)

    report_path = st.session_state.get("report_path")
    if report_path and Path(report_path).is_file():
        st.success("PDF 已生成，可以下载。")
        with open(report_path, "rb") as report_file:
            st.download_button(
                "下载 PDF 报告",
                data=report_file.read(),
                file_name=Path(report_path).name,
                mime="application/pdf",
                type="primary",
                width="stretch",
            )
        # 不回显服务器绝对路径：容器里会是 /app/data/reports/xxx.pdf，
        # 对用户既点不了也找不到，还暴露了部署目录结构。
        st.caption(f"文件名：{Path(report_path).name}")
    notice("报告用途", "报告为科研原型输出，应在正式提交或对外使用前复核企业数据、因子来源与适用政策。", amber=True)


def _generate_report(result: dict) -> None:
    try:
        from src.ui.components.report import generate_carbon_report

        llm_answer = next(
            (
                message["content"]
                for message in reversed(st.session_state.get("messages", []))
                if message["role"] == "assistant"
            ),
            "",
        )
        budget = result.get("carbon_budget", {})
        report_path = generate_carbon_report(
            company_name=st.session_state.get("company_name", "示例物流公司"),
            total_emission_t=result.get("total_emission_t", 0),
            total_vehicles=result.get("total_vehicles", 0),
            emission_by_type=result.get("emission_by_type", {}),
            total_quota_t=budget.get("模拟碳预算_t", 0),
            gap_t=budget.get("预算差额_t", 0),
            gap_status=budget.get("状态", "未知"),
            compliance_cost=result.get("scenario_cost", {}),
            llm_answer=llm_answer,
            budget_reduction_target=budget.get("情景减排目标", 0.10),
        )
        st.session_state.report_path = str(report_path)
    except Exception as exc:
        st.error(f"报告生成失败：{exc}")
