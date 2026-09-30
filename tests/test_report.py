"""PDF 报告关键字段与口径测试。"""

import fitz

from src.engine.carbon_price import estimate_compliance_cost
from src.ui.components.report import FONT_REGISTERED, generate_carbon_report


def test_report_uses_budget_value_and_research_disclaimer(tmp_path):
    output = tmp_path / "report.pdf"
    report_path = generate_carbon_report(
        company_name="测试物流公司",
        total_emission_t=3508.0,
        total_vehicles=50,
        emission_by_type={
            "重型柴油货车": {
                "排放量_tCO2": 3508.0,
                "占比": 100.0,
                "车辆数": 50,
                "排放因子_kg_per_km": 0.877,
                "燃料类型": "柴油",
            }
        },
        total_quota_t=3157.2,
        gap_t=350.8,
        gap_status="超出预算",
        compliance_cost=estimate_compliance_cost(350.8),
        output_path=str(output),
    )

    document = fitz.open(report_path)
    text = "\n".join(page.get_text() for page in document)

    assert len(document) == 3
    assert "3,157.20" in text
    assert "-350.80" not in text
    assert "10%" in text
    if FONT_REGISTERED:
        assert "科研原型" in text
        assert "可交易资产" in text
        assert "购电间接排放" in text
        assert "第 1 页" in text
    assert "tCO₂" not in text


def test_build_defense_pdfs_generation(tmp_path):
    """验证中期进展说明书与答辩指南 PDF 能够成功编译并包含核心合规要点"""
    from scripts.build_defense_pdfs import build_manual_pdf, build_guide_pdf

    manual_path = tmp_path / "manual.pdf"
    guide_path = tmp_path / "guide.pdf"

    build_manual_pdf(manual_path)
    build_guide_pdf(guide_path)

    assert manual_path.exists() and manual_path.stat().st_size > 1000
    assert guide_path.exists() and guide_path.stat().st_size > 1000

    doc_manual = fitz.open(manual_path)
    assert len(doc_manual) >= 3
    text_manual = "\n".join(page.get_text() for page in doc_manual)
    assert "4.23%" in text_manual
    assert "Wilcoxon" in text_manual

    doc_guide = fitz.open(guide_path)
    assert len(doc_guide) >= 2
    text_guide = "\n".join(page.get_text() for page in doc_guide)
    assert "00:00" in text_guide
