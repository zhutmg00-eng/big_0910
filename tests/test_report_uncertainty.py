"""PDF 报告必须带上不确定性区间，而不是把 P5/P95 留在界面上。"""
import os
import sys

sys.path.insert(0, os.getcwd())

import fitz

from src.ui.components.report import generate_carbon_report


def _text(path):
    """用 PyMuPDF 抽全文（项目已依赖它，见 tests/test_report.py）。"""
    with fitz.open(path) as document:
        return "\n".join(page.get_text() for page in document)


EMISSION_BY_TYPE = {
    "重型柴油货车": {"车辆数": 10, "排放量_tCO2": 210.0, "活动水平": "80000 km"},
    "轻型柴油货车": {"车辆数": 5, "排放量_tCO2": 20.0, "活动水平": "10000 km"},
}

UNCERTAINTY = {
    "point_estimate_t": 230.0,
    "mean_t": 234.5,
    "p5_t": 198.0,
    "p50_t": 233.0,
    "p95_t": 271.0,
    "relative_uncertainty_pct": 15.9,
    "contributions": {"排放因子·重型柴油货车": 0.7, "年均里程·重型柴油货车": 0.3},
    "variance_contributions": {"排放因子·重型柴油货车": 0.612, "年均里程·重型柴油货车": 0.281},
}

META = {"n_samples": 20000, "data_quality": "台账"}


def _build(tmp_path, uncertainty, meta=None):
    path = str(tmp_path / "r.pdf")
    generate_carbon_report(
        company_name="测试物流",
        total_emission_t=230.0,
        total_vehicles=15,
        emission_by_type=EMISSION_BY_TYPE,
        total_quota_t=200.0,
        gap_t=30.0,
        gap_status="超出模拟碳预算",
        compliance_cost={"情景判断": "超出模拟碳预算", "预算差额_t": 30.0,
                         "当前碳价_元每吨": 98.32, "情景成本_参考价": 2949.6},
        uncertainty=uncertainty,
        uncertainty_meta=meta,
        output_path=path,
    )
    return _text(path)


def test_report_carries_p5_p95_when_uncertainty_given(tmp_path):
    text = _build(tmp_path, UNCERTAINTY, META)
    assert "不确定性区间" in text
    assert "P5" in text and "P95" in text
    # 数值要能对上，不能只印标签
    assert "271" in text and "198" in text
    assert "±15.9%" in text


def test_report_states_sampling_settings(tmp_path):
    text = _build(tmp_path, UNCERTAINTY, META)
    assert "20,000" in text or "20000" in text
    assert "台账" in text


def test_report_names_top_variance_source(tmp_path):
    text = _build(tmp_path, UNCERTAINTY, META)
    # 优先改进建议必须来自一阶方差贡献，而不是秩相关分布
    assert "优先改进" in text
    assert "61.2%" in text


def test_report_says_not_run_when_uncertainty_missing(tmp_path):
    text = _build(tmp_path, None)
    assert "本次未运行" in text
    # 没跑就得说没跑，不能悄悄省略整段让读者以为不存在不确定性
    assert "不含不确定性区间" in text


def test_report_without_meta_still_renders(tmp_path):
    text = _build(tmp_path, UNCERTAINTY, None)
    assert "P95" in text
    assert "抽样设置" not in text
