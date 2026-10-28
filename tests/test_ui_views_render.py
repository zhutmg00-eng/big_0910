"""答辩演示所依赖的三个 UI 视图必须有「渲染不抛异常 + 关键字段透传」级测试。

背景（2026-10-27，I-2）：
`src/ui/views/advisory.py`（政策顾问 + 报告导出）与 `src/ui/views/validation.py`
（方法与验证页，答辩演示主页面之一）此前 0% 覆盖——`pytest --cov=src` 里两者
为 0%，而中期答辩演示恰恰主要走这几页。页面抛异常只能靠现场手点才能发现。

本文件用 `streamlit.testing.v1.AppTest` 的 bare 模式（`from_string`）渲染视图函数，
全部走假后端（不发起真实网络请求），断言三件事：
1. 渲染不抛异常；
2. 后端返回的关键字段（answer / retrieved_sources / evidence_warning）透传到页面；
3. 后端不可用时给出可读错误而不是空白。

口径注意：这里测的是视图层透传，不重新验证计算引擎（那是 tests/test_calculator.py
的职责），也不验证后端接口本身（tests/test_api.py）。
"""
from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[1]

BOOT = f"import sys\nsys.path.insert(0, {str(REPO_ROOT)!r})\n"


def _run_app(script: str, timeout: int = 120):
    from streamlit.testing.v1 import AppTest

    at = AppTest.from_string(BOOT + script, default_timeout=timeout)
    at.run()
    assert not at.exception, f"渲染抛异常：{[e.value for e in at.exception]}"
    return at


def _page_text(at) -> str:
    parts = [m.value for m in at.markdown]
    parts += [w.value for w in at.warning]
    parts += [e.value for e in at.error]
    parts += [i.value for i in at.info]
    parts += [s.value for s in at.success]
    # st.caption 承载了大量口径说明（「这是可溯源性，不是忠实度」这类），
    # 漏掉它会让人以为页面没写，测试就会对着一句批评却没被渲染的话反复失败。
    parts += [c.value for c in at.caption]
    return "\n".join(parts)


# ---------------------------------------------------------------- validation.py

class TestValidationPage:
    """方法与验证页直接读仓库台账文件，不需要后端。"""

    def test_renders_rq1_and_rq2_from_repo_ledgers(self):
        at = _run_app(
            "from src.ui.views.validation import render_validation\n"
            "render_validation()\n"
        )
        text = _page_text(at)
        assert "方法与验证" in text
        assert "真实车队对标" in text, "RQ1 小节缺失——derived_metrics.json 读取或渲染断了"
        assert "政策检索评测" in text, "RQ2 小节缺失——rag_retrieval_experiment_results.json 读取或渲染断了"

    def test_metric_values_pass_through_from_ledger(self):
        """页面上的数字必须来自台账，而不是写死的字符串。"""
        import json

        derived = json.loads((REPO_ROOT / "docs" / "derived_metrics.json").read_text(encoding="utf-8"))
        m = derived["mape"]
        at = _run_app(
            "from src.ui.views.validation import render_validation\n"
            "render_validation()\n"
        )
        labels = [mm.label for mm in at.metric]
        assert any("标定点误差" in lb for lb in labels), f"指标卡缺失：{labels}"
        values = [mm.value for mm in at.metric]
        assert any(f"{m['equal_weight_pct']:.2f}%" in v for v in values), (
            f"等权 MAPE {m['equal_weight_pct']}% 未透传到指标卡：{values}"
        )

    def test_missing_result_files_show_guidance_not_crash(self, tmp_path, monkeypatch):
        """两个台账文件都不存在时，页面要给出补救指引而不是异常。

        注意：AppTest 的 bare 模式在**同一进程**里执行脚本，所以不能在脚本里
        直接写 `val.RAG_RESULTS = ...`——那会改掉真实模块，污染同文件后续测试
        （实测：把 RAG_RESULTS 指向临时空路径后，后面「负例集应展示」的断言
        全部失败，但单独跑该测试却通过）。这里用 monkeypatch 修改并自动还原。
        """
        import src.ui.views.validation as val

        monkeypatch.setattr(val, "RAG_RESULTS", tmp_path / "no_rag.json")
        monkeypatch.setattr(val, "DERIVED", tmp_path / "no_derived.json")

        at = _run_app(
            "from src.ui.views.validation import render_validation\n"
            "render_validation()\n"
        )
        text = _page_text(at)
        assert "尚未生成评测结果" in text, "缺 RAG 结果时应给出复现指引"
        assert "evaluate_rag_benchmark.py" in text


# ---------------------------------------------------------------- advisory.py

ASK_PAYLOAD = {
    "answer": "物流运输行业目前未纳入全国碳市场配额管理。",
    "retrieved_sources": [
        {
            "source": "交通运输碳达峰实施方案.md",
            "date": "2022-01-19",
            "relevance": 0.91,
            "relevance_basis": "score",
            "chunk_id": "交通运输碳达峰实施方案.md_0",
            "excerpt": "加快推进运输工具装备低碳转型……",
            "retrievers": ["bm25", "keyword"],
        }
    ],
    "evidence_warning": "",
    "latency_ms": 12.3,
}


class TestPolicyAdvisorPage:
    """政策顾问页的视图层行为。

    所有后端替身都用 monkeypatch 装到模块上、测试结束自动还原。
    早期版本在 bare 脚本里直接 `adv.api_post = ...`，那是**同进程全局赋值**，
    执行完不会还原，后续测试会拿到上一个测试留下的替身。
    """

    @pytest.fixture(autouse=True)
    def _isolate_backend(self, monkeypatch):
        """默认把后端替身置为「连接失败」，避免任何测试意外打到真实 8000 端口。"""
        import requests

        import src.ui.views.advisory as adv

        def _refused(path, payload):
            raise requests.ConnectionError("refused")

        monkeypatch.setattr(adv, "api_post", _refused)

    def _render(self, api_post):
        import src.ui.views.advisory as adv

        adv.api_post = api_post
        return _run_app(
            "from src.ui.views.advisory import render_policy_advisor\n"
            "render_policy_advisor()\n"
        )

    def test_empty_state_offers_sample_questions(self):
        at = _run_app(
            "from src.ui.views.advisory import render_policy_advisor\n"
            "render_policy_advisor()\n"
        )
        text = _page_text(at)
        assert "还没有检索记录" in text
        buttons = [b.label for b in at.button]
        assert any("全国碳市场" in b for b in buttons), f"示例问题按钮缺失：{buttons}"

    def test_answer_and_sources_pass_through(self):
        """后端返回的 answer / sources / evidence_warning 必须逐字段透传。"""

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return ASK_PAYLOAD

        at = self._render(lambda path, payload: FakeResponse())
        assert at.chat_input, "政策顾问页必须有提问输入框"
        at.chat_input[0].set_value("物流企业是否纳入全国碳市场？").run()
        assert not at.exception

        text = _page_text(at)
        assert ASK_PAYLOAD["answer"] in text, "回答正文未透传到页面"
        assert "交通运输碳达峰实施方案.md" in text, "证据来源文件名未透传"
        assert "交通运输碳达峰实施方案.md_0" in text, "分块 ID 未透传"
        assert "BM25" in text and "字面规则" in text, "命中检索器标签未透传"
        history = at.session_state["messages"]
        roles = [m["role"] for m in history]
        assert roles == ["user", "assistant"], f"对话历史记录不完整：{roles}"

    def test_empty_sources_warn_instead_of_silent(self):
        """空证据必须显式告警——这是「无证据守卫」在视图层的最后防线。"""
        payload = {**ASK_PAYLOAD, "retrieved_sources": [],
                   "evidence_warning": "本次没有找到可引用的政策条款。"}

        class FakeResponse:
            status_code = 200

            @staticmethod
            def json():
                return payload

        at = self._render(lambda path, payload: FakeResponse())
        at.chat_input[0].set_value("完全不相关的问题").run()
        warns = [w.value for w in at.warning]
        assert any("没有找到可引用的政策条款" in w for w in warns), (
            f"空证据未告警：{warns}"
        )

    def test_backend_down_shows_readable_error(self):
        """后端不可用时给出可读错误，而不是空白页或堆栈。"""
        import requests

        def boom(path, payload):
            raise requests.ConnectionError("refused")

        at = self._render(boom)
        at.chat_input[0].set_value("问题").run()
        assert not at.exception, "RequestException 不应逃逸成页面异常"
        errors = [e.value for e in at.error]
        assert errors, "后端宕机时必须出现错误提示"
        assert any("8000" in e or "后端" in e or "启动" in e for e in errors), errors

    def test_http_error_surfaces_status_code(self):
        """非 200 响应走 show_api_error，让用户看到状态码与含义。"""

        class FakeResponse:
            status_code = 401

            @staticmethod
            def json():
                return {"detail": "API key 无效"}

        at = self._render(lambda path, payload: FakeResponse())
        at.chat_input[0].set_value("问题").run()
        errors = [e.value for e in at.error]
        assert any("401" in e for e in errors), f"401 未透传到错误提示：{errors}"


class TestReportPage:
    RESULT = {
        "company_name": "示例物流运输有限公司",
        "total_emission_t": 3352.8,
        "total_vehicles": 100,
        "emission_by_type": {},
        "carbon_budget": {"预算差额_t": 342.1, "状态": "超出模拟碳预算"},
        "scenario_cost": {},
        "methodology_note": "科研原型",
    }

    def test_empty_state_redirects_to_inventory(self):
        at = _run_app(
            "from src.ui.views.advisory import render_report\n"
            "render_report()\n"
        )
        text = _page_text(at)
        assert "暂无可导出的核算结果" in text
        buttons = [b.label for b in at.button]
        assert any("排放盘点" in b for b in buttons), f"跳转按钮缺失：{buttons}"

    def test_metrics_pass_through_from_carbon_result(self):
        script = (
            "import streamlit as st\n"
            f"st.session_state['carbon_result'] = {self.RESULT!r}\n"
            "st.session_state['company_name'] = '示例物流运输有限公司'\n"
            "from src.ui.views.advisory import render_report\n"
            "render_report()\n"
        )
        at = _run_app(script)
        values = [m.value for m in at.metric]
        joined = "\n".join(values)
        assert "3,353" in joined, f"排放总量未透传：{values}"
        assert "+342" in joined, f"预算差额未透传：{values}"
        assert "3,352.8" not in joined.replace("3,353", ""), "指标应按千分位格式化"


# ---------------------------------------------------------------- 新增评测指标的展示（I-7）

class TestNewMetricsSurfaced:
    """新接入的负例集与可溯源性指标必须在答辩演示页可见。

    否则会出现「数据算出来了、报告里写了、但评委在系统里看不到」的情况——
    评审只能靠翻 JSON 才知道我们做了这件事。
    """

    def _render(self):
        return _run_app(
            "from src.ui.views.validation import render_validation\n"
            "render_validation()\n"
        )

    def test_negative_suite_section_present(self):
        text = _page_text(self._render())
        assert "反事实负例集" in text, "30 题负例集指标未在验证页展示"
        assert "负例依据召回率" in text, "未说明该指标的准确含义"

    def test_negative_suite_never_called_refusal_rate(self):
        at = self._render()
        text = _page_text(at)
        for line in text.splitlines():
            if "拒答率" not in line:
                continue
            assert any(neg in line for neg in ("不称其为", "不是", "非拒答")), (
                f"验证页把负例检索命中说成了拒答率：{line.strip()[:120]}"
            )

    def test_grounding_metrics_present_with_scope_note(self):
        at = self._render()
        labels = [m.label for m in at.metric]
        assert any("引用文件名可溯源" in lb for lb in labels), f"缺少可溯源指标卡：{labels}"
        assert any("数值可溯源" in lb for lb in labels), f"缺少数值可溯源指标卡：{labels}"

        text = _page_text(at)
        assert "不是忠实度" in text, "未声明该指标不是忠实度，容易被当成模型可信度证据"
        assert "按构造成立" in text, "未说明满分的成因（逐字摘录）"

    def test_negative_suite_discloses_superset(self):
        """页面上也要说清 30 题集是主集负例的超集，避免两处读数被相加。"""
        text = _page_text(self._render())
        assert "超集" in text
        assert "不可相加" in text
