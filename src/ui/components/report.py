"""物流碳排放与减排情景报告生成器（PDF）。

报告包含封面、执行摘要、分车型排放明细、模拟碳预算与情景成本分析。
"""
import os
import re
from datetime import datetime
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm, cm
from reportlab.lib.colors import HexColor, white
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, PageBreak, HRFlowable
)
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont

# ============================================================
# 中文字体注册
# ============================================================
FONT_REGISTERED = False
FONT_NAME = "Helvetica"  # 默认 fallback

#: Windows/Linux 文件名非法字符。原本只替换 "/"，实测企业名
#: ``A|B?C*D<E>F`` 会直接抛 ``OSError [Errno 22] Invalid argument``，
#: 而 ``顺丰:冷链`` 虽能建文件但生成的下载名语义混乱。
_ILLEGAL_FILENAME_CHARS = re.compile(r'[\\/:*?"<>|\r\n\t]')

_FONT_PATHS = [
    "C:/Windows/Fonts/msyh.ttc",
    "C:/Windows/Fonts/simsun.ttc",
    "C:/Windows/Fonts/simhei.ttf",
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "msyh.ttc"),
    os.path.join(os.environ.get("WINDIR", "C:\\Windows"), "Fonts", "simsun.ttc"),
    "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc",
    "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/noto-cjk/NotoSansCJK-Regular.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/Library/Fonts/Arial Unicode.ttf",
]
# 注意：v0.3 列表末尾的 DejaVuSans 不含中文字形，在 Linux/Docker 中会被"成功"注册，
# 导致 PDF 中文全部变成方框。v0.4 删除该项，并以 reportlab 内置 CID 字体兜底。


def _safe_filename(company_name: str, max_len: int = 60) -> str:
    """把企业名清洗为跨平台可用的文件名片段。

    原实现只替换 ``/``，实测企业名 ``A|B?C*D<E>F`` 在 Windows 上直接抛
    ``OSError [Errno 22] Invalid argument``，``顺丰:冷链`` 则生成带冒号的
    文件（LinuX 可用、Windows 不可用）。这里统一替换 Windows/Linux 全部
    非法字符，并截断到 60 字符，避免超出路径长度上限。
    """
    cleaned = _ILLEGAL_FILENAME_CHARS.sub("_", (company_name or "企业").strip())
    cleaned = cleaned.strip(". ") or "企业"
    return cleaned[:max_len]


def _register_chinese_font():
    """尝试注册中文字体，失败则回退到 Helvetica"""
    global FONT_REGISTERED, FONT_NAME

    for fpath in _FONT_PATHS:
        if os.path.exists(fpath):
            try:
                # 注册字体名
                if fpath.lower().endswith(".ttc"):
                    pdfmetrics.registerFont(TTFont("ChinaFont", fpath, subfontIndex=0))
                else:
                    pdfmetrics.registerFont(TTFont("ChinaFont", fpath))
                FONT_NAME = "ChinaFont"
                FONT_REGISTERED = True
                return
            except Exception:
                continue

    # 兜底：Adobe-GB1 CID 字体（reportlab 内置，无需任何字体文件，跨平台可用）
    try:
        from reportlab.pdfbase.cidfonts import UnicodeCIDFont

        pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
        FONT_NAME = "STSong-Light"
        FONT_REGISTERED = True
        return
    except Exception:
        pass
    FONT_NAME = "Helvetica"
    FONT_REGISTERED = False


# 初始化注册
_register_chinese_font()
if FONT_REGISTERED:
    # 中文字体没有独立粗体/斜体文件：把 <b>/<i> 映射回同一字体，避免 reportlab 报
    # “Can't map determine family/bold/italic”。
    from reportlab.lib.fonts import addMapping
    for _bold in (0, 1):
        for _italic in (0, 1):
            addMapping(FONT_NAME, _bold, _italic, FONT_NAME)

# ============================================================
# 样式定义
# ============================================================
_FONT = FONT_NAME


def _make_styles():
    """返回自定义段落样式"""
    styles = getSampleStyleSheet()

    # 封面标题样式
    styles.add(ParagraphStyle(
        name="CoverTitle",
        fontName=_FONT,
        fontSize=28,
        leading=36,
        alignment=TA_CENTER,
        spaceAfter=20,
    ))

    # 封面副标题
    styles.add(ParagraphStyle(
        name="CoverSub",
        fontName=_FONT,
        fontSize=14,
        leading=20,
        alignment=TA_CENTER,
        spaceAfter=10,
        textColor=HexColor("#555555"),
    ))

    # 一级标题
    styles.add(ParagraphStyle(
        name="SectionTitle",
        fontName=_FONT,
        fontSize=16,
        leading=22,
        spaceBefore=12,
        spaceAfter=8,
        textColor=HexColor("#1B5E20"),
        borderPadding=(0, 0, 2, 0),
    ))

    # 二级标题
    styles.add(ParagraphStyle(
        name="SubSectionTitle",
        fontName=_FONT,
        fontSize=13,
        leading=18,
        spaceBefore=8,
        spaceAfter=4,
        textColor=HexColor("#333333"),
    ))

    # 正文
    styles.add(ParagraphStyle(
        name="BodyTextCN",
        fontName=_FONT,
        fontSize=10,
        leading=16,
        alignment=TA_LEFT,
        spaceAfter=4,
    ))

    styles.add(ParagraphStyle(
        name="Disclaimer",
        fontName=_FONT,
        fontSize=9,
        leading=15,
        alignment=TA_LEFT,
        spaceBefore=6,
        spaceAfter=8,
        textColor=HexColor("#5D4037"),
        backColor=HexColor("#FFF8E1"),
        borderColor=HexColor("#FFCC80"),
        borderWidth=0.6,
        borderPadding=8,
    ))

    # 表格标题
    styles.add(ParagraphStyle(
        name="TableCaption",
        fontName=_FONT,
        fontSize=10,
        leading=14,
        spaceBefore=6,
        spaceAfter=4,
        textColor=HexColor("#666666"),
    ))

    return styles


# ============================================================
# 表格辅助函数
# ============================================================
_HEADER_BG = HexColor("#2E7D32")
_HEADER_FG = white
_ROW_BG = HexColor("#F1F8E9")
_ROW_ALT_BG = white
_TEXT_FG = HexColor("#333333")


def _build_table_style(col_count=5):
    """返回通用表格样式"""
    style_cmds = [
        ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#C8E6C9")),
        ("BACKGROUND", (0, 0), (-1, 0), _HEADER_BG),
        ("TEXTCOLOR", (0, 0), (-1, 0), _HEADER_FG),
        ("FONTNAME", (0, 0), (-1, 0), _FONT),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        ("FONTNAME", (0, 1), (-1, -1), _FONT),
        ("FONTSIZE", (0, 1), (-1, -1), 9),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [_ROW_BG, _ROW_ALT_BG]),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
    ]
    return style_cmds


def _fmt_number(val, decimals=2):
    """格式化数字"""
    if val is None:
        return "-"
    return f"{val:,.{decimals}f}"


# ============================================================
# 页眉页脚（闭包形式，捕获 company_name）
# ============================================================
def _make_page_callbacks(company_name):
    """创建页眉页脚回调函数"""
    def _footer(canvas, doc):
        """页脚：页码"""
        canvas.saveState()
        canvas.setFont(_FONT, 8)
        canvas.setFillColor(HexColor("#999999"))
        page_text = f"第 {doc.page} 页"
        canvas.drawCentredString(A4[0] / 2, 15 * mm, page_text)
        canvas.restoreState()

    def _header(canvas, doc):
        """页眉：企业名称"""
        canvas.saveState()
        canvas.setFont(_FONT, 8)
        canvas.setFillColor(HexColor("#1B5E20"))
        left_text = company_name or ""
        canvas.drawString(15 * mm, A4[1] - 12 * mm, left_text)
        canvas.restoreState()

    def _decorate(canvas, doc):
        _header(canvas, doc)
        _footer(canvas, doc)

    return _decorate


# ============================================================
# 报告生成核心函数
# ============================================================
def generate_carbon_report(
    company_name: str,
    total_emission_t: float,
    total_vehicles: int,
    emission_by_type: dict,
    total_quota_t: float,
    gap_t: float,
    gap_status: str,
    compliance_cost: dict,
    llm_answer: str = "",
    output_path: str = None,
    budget_reduction_target: float = 0.10,
    uncertainty: dict = None,
    uncertainty_meta: dict = None,
) -> str:
    """
    生成物流碳排放与减排情景 PDF 报告。

    Args:
        company_name: 企业名称
        total_emission_t: 直接运营排放量（tCO2e）
        total_vehicles: 总车辆数
        emission_by_type: 分车型排放明细 dict
        total_quota_t: 模拟碳预算（tCO2e）
        gap_t: 预算差额（正=超出，负=低于）
        gap_status: 模拟预算状态字符串
        compliance_cost: 碳价对标情景估算 dict（参数名为兼容旧调用保留）
        llm_answer: 政策建议（可选）
        output_path: 输出路径（可选）
        budget_reduction_target: 模拟预算相对参考活动排放的减排目标
        uncertainty: 蒙特卡洛结果 dict（p5_t/p50_t/p95_t/mean_t/relative_uncertainty_pct/
            contributions/variance_contributions），为 None 时报告写明"本次未运行"
        uncertainty_meta: 抽样设置（n_samples/data_quality），用于让区间可复算

    Returns:
        生成的 PDF 文件路径
    """
    # ---- 输出路径 ----
    if output_path is None:
        from src.config import DATA_DIR
        reports_dir = DATA_DIR / "reports"
        reports_dir.mkdir(parents=True, exist_ok=True)
        date_str = datetime.now().strftime("%Y%m%d")
        safe_name = _safe_filename(company_name)
        output_path = str(reports_dir / f"{safe_name}_报告_{date_str}.pdf")

    # ---- 构建 PDF ----
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
        leftMargin=18 * mm,
        rightMargin=18 * mm,
    )

    styles = _make_styles()
    elements = []
    width = A4[0] - 36 * mm  # 可用内容宽度

    # ---- 中文不可用提示 ----
    if not FONT_REGISTERED:
        elements.append(Paragraph(
            "（中文暂用英文字体渲染）",
            ParagraphStyle("Note", fontName="Helvetica", fontSize=8, textColor=HexColor("#999999")),
        ))
        elements.append(Spacer(1, 10 * mm))

    # ============================================================
    # 第1页 封面
    # ============================================================
    elements.append(Spacer(1, 50 * mm))
    elements.append(Paragraph("碳排放与减排情景报告", styles["CoverTitle"]))
    elements.append(Spacer(1, 15 * mm))
    elements.append(HRFlowable(width="60%", thickness=1, color=HexColor("#2E7D32")))
    elements.append(Spacer(1, 20 * mm))
    elements.append(Paragraph(f"企业名称：{company_name}", styles["CoverSub"]))
    elements.append(Paragraph(f"报告日期：{datetime.now().strftime('%Y年%m月%d日')}", styles["CoverSub"]))
    elements.append(Spacer(1, 10 * mm))
    elements.append(Paragraph(f"直接运营排放：{_fmt_number(total_emission_t)} tCO2e", styles["CoverSub"]))
    elements.append(Paragraph(f"总车辆数：{total_vehicles} 辆", styles["CoverSub"]))
    elements.append(Spacer(1, 38 * mm))
    elements.append(Paragraph(
        "科研原型自动生成 · 不作为法定核查、履约或交易依据",
        ParagraphStyle("Footer", fontName=_FONT, fontSize=9, textColor=HexColor("#999999"), alignment=TA_CENTER),
    ))
    elements.append(PageBreak())

    # ============================================================
    # 第2页 执行摘要
    # ============================================================
    elements.append(Paragraph("一、执行摘要", styles["SectionTitle"]))
    elements.append(Spacer(1, 6 * mm))

    # 核心指标表格
    core_data = [
        ["指标", "数值"],
        ["年度直接运营排放", f"{_fmt_number(total_emission_t)} tCO2e"],
        ["总车辆数", f"{total_vehicles} 辆"],
        ["模拟碳预算", f"{_fmt_number(total_quota_t)} tCO2e"],
        ["情景减排目标", f"{budget_reduction_target:.0%}"],
        ["预算差额", f"{_fmt_number(gap_t)} tCO2e（{gap_status}）"],
    ]

    # 碳价对标情景核心指标
    cost_title = compliance_cost.get("情景判断", "")
    if cost_title == "超出模拟碳预算":
        core_data.append(["情景成本（参考价）", f"{_fmt_number(compliance_cost.get('情景成本_参考价', 0), 0)} 元"])
        core_data.append(["参考碳价", f"{_fmt_number(compliance_cost.get('当前碳价_元每吨', 0))} 元/tCO2e"])
    elif cost_title in {"低于模拟碳预算", "基本平衡"}:
        core_data.append(["潜在价值区间", f"{_fmt_number(compliance_cost.get('潜在价值_low', 0), 0)} ~ {_fmt_number(compliance_cost.get('潜在价值_high', 0), 0)} 元"])
    else:
        core_data.append(["情景成本", "暂无数据"])

    t = Table(core_data, colWidths=[3.5 * cm, width - 3.5 * cm])
    t.setStyle(_build_table_style(2))
    elements.append(t)
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph(
        "重要口径：物流运输行业目前未纳入全国碳市场配额管理。本报告中的模拟碳预算、预算差额、情景成本和潜在价值仅用于科研对标，不代表法定配额、履约义务、可交易资产或实际收益。",
        styles["Disclaimer"],
    ))

    # 关键结论
    if gap_t > 0:
        elements.append(Paragraph(
            f"<b>情景结论：</b>直接运营排放高于模拟碳预算 <b>{_fmt_number(gap_t)} tCO2e</b>，"
            "可优先评估车队更新、路线优化和满载率提升等减排措施。",
            styles["BodyTextCN"],
        ))
    elif gap_t < 0:
        elements.append(Paragraph(
            f"<b>情景结论：</b>直接运营排放低于模拟碳预算 <b>{_fmt_number(abs(gap_t))} tCO2e</b>。"
            "该差额仅表示情景结余，不等同于可出售配额。",
            styles["BodyTextCN"],
        ))
    else:
        elements.append(Paragraph(
            "<b>情景结论：</b>企业直接运营排放与模拟碳预算基本平衡。",
            styles["BodyTextCN"],
        ))

    # ============================================================
    # 分车型排放明细
    # ============================================================
    elements.append(Paragraph("二、分车型排放明细", styles["SectionTitle"]))
    elements.append(Spacer(1, 6 * mm))

    emission_data = [["车型", "排放量 (tCO2e)", "占比 (%)", "车辆数 (辆)", "排放因子 (kg/km)"]]
    for vtype, info in emission_by_type.items():
        emission_data.append([
            vtype,
            f"{_fmt_number(info.get('排放量_tCO2', 0))}",
            f"{info.get('占比', 0)}",
            str(info.get("车辆数", 0)),
            f"{info.get('排放因子_kg_per_km', 0)}",
        ])

    t2 = Table(emission_data, colWidths=[3 * cm, 2.8 * cm, 2 * cm, 2.2 * cm, 3.4 * cm])
    t2.setStyle(_build_table_style(5))
    elements.append(t2)
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph(
        "新能源物流车在本模型中仅按车辆直接运营排放为 0 计算；购电间接排放、车辆制造与报废等全生命周期排放未纳入。",
        styles["Disclaimer"],
    ))

    # 按燃料类型分组说明
    fuel_groups = {}
    for vtype, info in emission_by_type.items():
        fuel = info.get("燃料类型", "未知")
        if fuel not in fuel_groups:
            fuel_groups[fuel] = {"排放量": 0, "车辆数": 0}
        fuel_groups[fuel]["排放量"] += info.get("排放量_tCO2", 0)
        fuel_groups[fuel]["车辆数"] += info.get("车辆数", 0)

    if fuel_groups and total_emission_t > 0:
        elements.append(Paragraph("按燃料类型汇总", styles["SubSectionTitle"]))
        fuel_data = [["燃料类型", "排放量 (tCO2e)", "占比 (%)", "车辆数 (辆)"]]
        for fuel, vals in fuel_groups.items():
            fuel_data.append([
                fuel,
                f"{_fmt_number(vals['排放量'])}",
                f"{round(vals['排放量'] / total_emission_t * 100, 1)}",
                str(vals["车辆数"]),
            ])
        t3 = Table(fuel_data, colWidths=[3 * cm, 3 * cm, 2 * cm, 2.5 * cm])
        t3.setStyle(_build_table_style(4))
        elements.append(t3)

    elements.append(PageBreak())

    # ============================================================
    # 模拟碳预算与情景成本分析
    # ============================================================
    elements.append(Paragraph("三、模拟碳预算与情景成本", styles["SectionTitle"]))
    elements.append(Spacer(1, 6 * mm))

    # 模拟碳预算对比表
    quota_data = [["项目", "数值 (tCO2e)"],
                  ["模拟碳预算", f"{_fmt_number(total_quota_t)}"],
                  ["直接运营排放", f"{_fmt_number(total_emission_t)}"],
                  ["预算差额", f"{_fmt_number(gap_t)}（{gap_status}）"]]
    t4 = Table(quota_data, colWidths=[4 * cm, width - 4 * cm])
    t4.setStyle(_build_table_style(2))
    elements.append(t4)
    elements.append(Spacer(1, 8 * mm))

    # 分车型模拟预算明细
    elements.append(Paragraph("分车型模拟预算明细", styles["SubSectionTitle"]))

    # 从 emission_by_type 获取车辆数
    fleet_summary = {}
    for vtype, info in emission_by_type.items():
        fleet_summary[vtype] = info.get("车辆数", 0)

    # 配额基准值
    from src.engine.quota import build_simulation_budget_benchmarks
    budget_benchmarks = build_simulation_budget_benchmarks(budget_reduction_target)
    quota_detail_data = [["车型", "车辆数", "预算基准", "模拟预算", "直接排放", "预算差额"]]
    for vtype, info in emission_by_type.items():
        count = info.get("车辆数", 0)
        benchmark = budget_benchmarks.get(vtype, 0)
        type_quota = count * benchmark
        type_emission = info.get("排放量_tCO2", 0)
        # 与全局 Gap = E - B 保持一致：正值表示超出模拟预算。
        diff = type_emission - type_quota
        quota_detail_data.append([
            vtype,
            str(count),
            f"{_fmt_number(benchmark)}",
            f"{_fmt_number(type_quota)}",
            f"{_fmt_number(type_emission)}",
            f"{_fmt_number(diff)}",
        ])

    t5 = Table(quota_detail_data, colWidths=[3 * cm, 1.8 * cm, 2 * cm, 2 * cm, 2 * cm, 2.2 * cm])
    t5.setStyle(_build_table_style(6))
    elements.append(t5)
    elements.append(Spacer(1, 8 * mm))

    # 碳价对标情景
    elements.append(Paragraph("碳价对标情景", styles["SubSectionTitle"]))

    cost_table_data = [["指标", "数值"]]
    cost_title = compliance_cost.get("情景判断", "")
    if cost_title == "超出模拟碳预算":
        cost_table_data.append(["预算差额", f"{_fmt_number(compliance_cost.get('预算差额_t', gap_t))} tCO2e"])
        cost_table_data.append(["当前碳价", f"{_fmt_number(compliance_cost.get('当前碳价_元每吨', 0))} 元/tCO2e"])
        cost_table_data.append(["近90日均价", f"{_fmt_number(compliance_cost.get('近90日均价_元每吨', 0))} 元/tCO2e"])
        cost_table_data.append(["碳价离散度(CV)", compliance_cost.get("碳价离散度CV", "-")])
        cost_table_data.append(["情景成本（参考价）", f"{_fmt_number(compliance_cost.get('情景成本_参考价', 0), 0)} 元"])
        cost_table_data.append(["情景成本区间",
                                f"{_fmt_number(compliance_cost.get('情景成本区间_low', 0), 0)} ~ "
                                f"{_fmt_number(compliance_cost.get('情景成本区间_high', 0), 0)} 元"])
    elif cost_title in {"低于模拟碳预算", "基本平衡"}:
        cost_table_data.append(["预算结余", f"{_fmt_number(compliance_cost.get('预算结余_t', abs(gap_t)))} tCO2e"])
        cost_table_data.append(["参考碳价", f"{_fmt_number(compliance_cost.get('参考碳价_元每吨', 0))} 元/tCO2e"])
        cost_table_data.append(["潜在价值区间",
                                f"{_fmt_number(compliance_cost.get('潜在价值_low', 0), 0)} ~ "
                                f"{_fmt_number(compliance_cost.get('潜在价值_high', 0), 0)} 元"])
    else:
        cost_table_data.append(["情景判断", cost_title])

    t6 = Table(cost_table_data, colWidths=[4 * cm, width - 4 * cm])
    t6.setStyle(_build_table_style(2))
    elements.append(t6)

    elements.append(Paragraph(compliance_cost.get("备注", ""), styles["Disclaimer"]))

    # ============================================================
    # 不确定性区间（蒙特卡洛）
    # ============================================================
    # 此前 P5/P95 只在界面图上显示，进不了 PDF。区间恰恰是"这份数字能不能
    # 拿去对外"的关键：点估计 1,352 t 与 90% 区间 1,180–1,560 t 是两件事。
    elements.append(Spacer(1, 8 * mm))
    elements.append(Paragraph("排放量的不确定性区间", styles["SubSectionTitle"]))

    if not uncertainty or not uncertainty.get("p95_t"):
        elements.append(Paragraph(
            "本次未运行为蒙特卡洛抽样，报告中的排放量为点估计，不含不确定性区间。"
            "如需给出区间，请在「排放盘点 → 不确定性分析」中运行蒙特卡洛后重新生成本报告。",
            styles["BodyTextCN"],
        ))
    else:
        meta = uncertainty_meta or {}
        p5 = uncertainty.get("p5_t", 0.0)
        p50 = uncertainty.get("p50_t", 0.0)
        p95 = uncertainty.get("p95_t", 0.0)
        mean_t = uncertainty.get("mean_t", 0.0)
        rel = uncertainty.get("relative_uncertainty_pct", 0.0)
        unc_data = [["指标", "数值"],
                    ["点估计（确定性核算）", f"{_fmt_number(total_emission_t)} tCO2e"],
                    ["抽样均值", f"{_fmt_number(mean_t)} tCO2e"],
                    ["P5（下界）", f"{_fmt_number(p5)} tCO2e"],
                    ["P50（中位数）", f"{_fmt_number(p50)} tCO2e"],
                    ["P95（上界）", f"{_fmt_number(p95)} tCO2e"],
                    ["90% 区间", f"{_fmt_number(p5)} ~ {_fmt_number(p95)} tCO2e"],
                    ["相对不确定度", f"±{rel:.1f}%"]]
        if meta:
            settled = []
            if meta.get("n_samples"):
                settled.append(f"抽样 {int(meta['n_samples']):,} 次")
            if meta.get("data_quality"):
                settled.append(f"活动数据质量「{meta['data_quality']}」")
            if settled:
                unc_data.append(["抽样设置", "，".join(settled)])
        t_unc = Table(unc_data, colWidths=[4 * cm, width - 4 * cm])
        t_unc.setStyle(_build_table_style(2))
        elements.append(t_unc)
        elements.append(Spacer(1, 4 * mm))

        # 哪一项数据最值得先改进：用一阶方差贡献（可加、可比较），
        # 底部的秩相关 contributions 只能同案例内排序，不能回答这个问题。
        variance_contrib = uncertainty.get("variance_contributions") or {}
        if variance_contrib:
            ranked = sorted(variance_contrib.items(), key=lambda kv: kv[1], reverse=True)[:3]
            contrib_data = [["不确定性来源（一阶方差贡献）", "占比"]]
            for name, share in ranked:
                contrib_data.append([str(name), f"{share * 100:.1f}%"])
            t_contrib = Table(contrib_data, colWidths=[width - 3.5 * cm, 3.5 * cm])
            t_contrib.setStyle(_build_table_style(2))
            elements.append(t_contrib)
            elements.append(Spacer(1, 3 * mm))
            top = ranked[0]
            elements.append(Paragraph(
                f"优先改进「{top[0]}」：它贡献了排放量方差的 {top[1] * 100:.1f}%，"
                "用实测台账或 GPS 数据替换该项估计值，区间收窄最明显。",
                styles["BodyTextCN"],
            ))
        elements.append(Paragraph(
            "区间来自排放因子三角分布与活动数据误差的蒙特卡洛抽样，反映的是输入数据本身的不确定性，"
            "不含模型形式误差（例如核算边界的选择）。点估计与 P50 的差异说明抽样均值与确定性核算口径不同。",
            styles["Disclaimer"],
        ))

    # 政策资料提示（可选）
    if llm_answer and llm_answer.strip():
        elements.append(Paragraph("四、政策资料提示", styles["SectionTitle"]))
        elements.append(Spacer(1, 6 * mm))

        # 按段落分割
        for line in llm_answer.strip().split("\n"):
            line = line.strip()
            if line:
                elements.append(Paragraph(line, styles["BodyTextCN"]))

    method_section = "五、方法边界" if llm_answer and llm_answer.strip() else "四、方法边界"
    elements.append(Paragraph(method_section, styles["SectionTitle"]))
    elements.append(Paragraph(
        "本报告用于项目研究、方案比较和方法验证。正式披露或企业决策前，应由具备资质的专业机构依据适用标准补充燃料实测数据、购电间接排放、运输周转量及全生命周期边界，并复核政策时效性。",
        styles["BodyTextCN"],
    ))

    # ============================================================
    # 生成 PDF
    # ============================================================
    page_cb = _make_page_callbacks(company_name)
    doc.build(
        elements,
        onFirstPage=page_cb,
        onLaterPages=page_cb,
    )

    return output_path
