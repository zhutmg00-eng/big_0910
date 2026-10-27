"""对外声称的数字必须与数据台账一致。

本项目历史上出现过同一数字三种口径名（4.23% 被称"全样本 MAPE"/"等权 MAPE"/"加权"）、
以及图上的误差区间（2.88%~5.20%）与正文（1.66%~7.27%）互相矛盾的情况。
本文件把「对外声称值」与「docs/derived_metrics.json 台账」锁在一起，
任何一侧漂移都会让测试失败，从而在提交前就暴露出来。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT
_COLLECTED_CACHE = None
METRICS = json.loads((ROOT / "docs" / "derived_metrics.json").read_text(encoding="utf-8"))


def _read(rel):
    return (ROOT / rel).read_text(encoding="utf-8")


def _read_private(rel):
    """读取**刻意不入库**的私有文书（论文、答辩材料、专家意见）。

    这些文件被 .gitignore 排除（见 .gitignore "私人研究、论文手稿与答辩私用文书
    产物" 一节），公开仓库与 CI 的全新 clone 里并不存在。因此这里不能直接用
    _read，否则 CI 必然 FileNotFoundError。

    回落到 skip 而不是静默通过，是为了让 CI 报告里明确可见"这部分口径校验未执行"，
    而不是假装校验过了。本地有材料时仍然照常严格校验。
    """
    path = ROOT / rel
    if not path.is_file():
        pytest.skip(f"{rel} 未入库（.gitignore 排除）或不存在，跳过该口径校验")
    return path.read_text(encoding="utf-8")


# 需要"存在才校验"的私有文书；集中登记便于审阅这批校验的实际覆盖面
PRIVATE_DOCS = (
    "docs/academic_paper.md",
    "docs/大创中期答辩核心指南与评审问辨应对.md",
    "docs/国家级优秀大创答辩逐字稿与尖锐质询策略_升级版.md",
    "docs/大创中期答辩幻灯片视觉与内容全景设计图解.md",
)


def test_mape_claims_match_ledger():
    """README/论文里的 4.23% 与 2.38% 必须等于台账算出的值。"""
    mape = METRICS["mape"]
    assert mape["n_cases"] == 4
    expected_equal = mape["equal_weight_pct"]
    expected_weighted = mape["emission_weight_pct"]

    paper = _read_private("docs/academic_paper.md")
    assert f"{expected_equal}%" in paper or f"{expected_equal}\\%" in paper, (
        f"论文未出现台账等权 MAPE {expected_equal}%"
    )
    assert f"{expected_weighted}%" in paper or f"{expected_weighted}\\%" in paper, (
        f"论文未出现台账加权 MAPE {expected_weighted}%"
    )


def test_error_range_claims_match_ledger():
    """论文中声称的误差区间必须与台账的 min/max 完全一致。"""
    mape = METRICS["mape"]
    lo, hi = mape["min_pct"], mape["max_pct"]
    paper = _read_private("docs/academic_paper.md")

    # 论文写法为 $+1.66\% \sim +7.27\%$，故需允许 \sim 与 LaTeX 转义百分号
    pattern = (
        rf"\+?{re.escape(str(lo))}\s*\\?%\s*"
        rf"(?:~|～|-|\\sim)\s*"
        rf"\+?{re.escape(str(hi))}"
    )
    assert re.search(pattern, paper), (
        f"论文未出现与台账一致的误差区间 {lo}%~{hi}%"
    )


def test_no_stale_error_range_in_paper():
    """早期草稿残留的错误区间（2.88%/5.20%）不得再出现在论文中。"""
    paper = _read_private("docs/academic_paper.md")
    for stale in ("2.88", "5.20%"):
        assert stale not in paper, f"论文仍残留早期草稿数值 {stale}"


def test_vehicle_total_claims_consistent():
    """论文与说明书引用的车辆总数必须等于台账合计。"""
    total = METRICS["mape"]["vehicles_total"]
    expected = f"{total:,}"
    for rel in ("docs/academic_paper.md", "docs/real_fleet_validation_report.md"):
        text = _read_defense(rel)
        assert expected in text, f"{rel} 未出现台账车辆总数 {expected}"


def test_no_sample_size_confusion_claim():
    """不得把 51,990 辆当作「实测样本量」——它是覆盖车辆数。"""
    paper = _read_private("docs/academic_paper.md")
    # 论文必须显式声明观测单元是 n=4 的车队级而非逐车
    assert "n=4" in paper or "n = 4" in paper, "论文未声明车队级观测单元 n=4"


def test_case_level_values_match_ledger():
    """论文表 4 的每个案例误差必须逐一对上台账。"""
    paper = _read_private("docs/academic_paper.md")
    for case in METRICS["fleet_cases"]:
        err = case["rel_err_pct"]
        sign = "+" if err >= 0 else ""
        token = f"{sign}{err}%"
        assert token in paper, f"论文表 4 缺少案例 {case['id']} 的误差 {token}"


# ---------- 图表产物：数字必须与台账一致，且不得有早期草稿残留 ----------

STALE_FIGURE_CLAIMS = ("2.88", "5.20", "高稳定性")


def test_figure_artifacts_render_ledger_range():
    """fig1 的结论条必须渲染台账区间；若模板用普通字符串会被原样写出 \u007bERR_LO\u007d。"""
    svg = _read("docs/artifacts/fig1_rq1_real_fleet_validation.svg")
    lo, hi = METRICS["mape"]["min_pct"], METRICS["mape"]["max_pct"]
    assert f"[+{lo}%, +{hi}%]" in svg, (
        f"fig1 未渲染台账偏差区间 [+{lo}%, +{hi}%]，检查模板是否为 f-string"
    )


def test_figure_artifacts_have_no_unrendered_placeholders():
    """占位符被原样写出说明该段字符串漏了 f 前缀。"""
    for rel in (
        "docs/artifacts/fig1_rq1_real_fleet_validation.svg",
        "docs/artifacts/fig2_rq2_rag_benchmark_comparison.svg",
        "docs/artifacts/fig3_rq3_sensitivity_heatmap.svg",
        "docs/artifacts/all_charts_dashboard.html",
    ):
        text = _read_defense(rel)
        for token in ("{ERR_LO", "{ERR_HI", "{MAPE_EQ", "{MAPE_WT", "{LF_NO_BIAS", "{KB_DOCS"):
            assert token not in text, f"{rel} 仍含未渲染占位符 {token}"


def test_figure_artifacts_have_no_stale_claims():
    """早期草稿的 2.88%/5.20%/「高稳定性」不得重新出现在图表产物中。"""
    for rel in (
        "docs/artifacts/fig1_rq1_real_fleet_validation.svg",
        "docs/artifacts/fig1_rq1_real_fleet_validation.html",
        "docs/artifacts/all_charts_dashboard.html",
    ):
        text = _read_defense(rel)
        for stale in STALE_FIGURE_CLAIMS:
            assert stale not in text, f"{rel} 仍含早期草稿数值/表述 {stale}"


def test_dashboard_kb_badge_matches_actual_corpus():
    """展板上的知识库规模徽标必须来自运行时实测，而不是写死的 37/268 旧快照。"""
    dashboard = _read("docs/artifacts/all_charts_dashboard.html")
    assert "37 份法规" not in dashboard, "展板仍使用 v0.4 旧快照的 37 份法规"
    assert "268 Chunks" not in dashboard, "展板仍使用 v0.4 旧快照的 268 Chunks"

    # 若知识库已建，徽标必须与 PolicyVectorStore.count() 一致
    try:
        import sys

        sys.path.insert(0, str(ROOT))
        from src.rag.vector_store import PolicyVectorStore

        actual = int(PolicyVectorStore().count())
    except Exception:
        return  # 未建库时跳过精确比对，仅做旧值守卫

    if actual <= 0:
        # 空库（全新 clone 未跑 ingest）时 count() 返回 0 而不是抛异常，
        # 此时"徽标必须含 0 Chunks"没有意义，跳过精确比对。
        return

    assert f"{actual} Chunks" in dashboard, (
        f"展板徽标与实测块数 {actual} 不一致"
    )


# ---------------------------------------------------------------------------
# RAG 指标守卫（2026-10 补）
#
# 历史问题：答辩材料曾写"MRR 从 0.0411 提升至 0.8171（提升近 20 倍）"。
# 实测追查表明 0.8171 根本不是任何方案的 MRR，而是
# docs/rag_benchmark/rag_retrieval_experiment_results.json 里
# detailed_results.hybrid[36] 这一道题在 hybrid 模式下的 ndcg10
# （0.8175295903539445）。同时 0.0411 是 ChromaDB 默认【英文】嵌入
# all-MiniLM-L6-v2 的纯向量 MRR，与中文 bge 不是同一实验设置。
# 下面的测试把这个错误口径钉死，防止答辩材料再次漂移。
# ---------------------------------------------------------------------------
RAG_RESULTS = json.loads(
    (ROOT / "docs" / "rag_benchmark" / "rag_retrieval_experiment_results.json").read_text(
        encoding="utf-8"
    )
)

# 答辩类材料：这些文件是直接对外讲述的，数字必须与实测一致。
#
# 【2026-10-21 扩容说明】原名单只有 3 份 .md，而这三份恰恰被 .gitignore 排除，
# 于是在公开仓库里 12/16 条口径守卫全部 skip——守卫守住了「作者本机已清理过的文件」，
# 却放过了「真正公开、真正被评委打开的产物」。
# 新登记的 2 份是公开仓库里的直接载体（git ls-files 确认在库），
# 被证伪的「0.8171 / 近 20 倍 / 100% 拒答 / 37 份 268 Chunk / Kappa=1.0 / 4.905 分 / 107 项」
# 曾完整存活在这两个文件里。加进来之后守卫会立刻变红，这正是它应该做的事。
DEFENSE_DOCS = (
    "docs/大创中期答辩核心指南与评审问辨应对.md",
    "docs/国家级优秀大创答辩逐字稿与尖锐质询策略_升级版.md",
    "docs/大创中期答辩幻灯片视觉与内容全景设计图解.md",
    "docs/artifacts/defense_presentation_deck.html",
    "scripts/generate_presentation_pptx.py",
)

# 公开载体不是私有文书：它们必须在仓库里，缺失即是缺陷（而不是 skip）。
PUBLIC_DEFENSE_DOCS = (
    "docs/artifacts/defense_presentation_deck.html",
    "scripts/generate_presentation_pptx.py",
)


def _read_defense(rel):
    """公开载体缺失要判失败；私有文书缺失才允许 skip。"""
    if rel in PUBLIC_DEFENSE_DOCS:
        path = ROOT / rel
        assert path.exists(), f"{rel} 是对外公开载体，必须存在于仓库中"
        return path.read_text(encoding="utf-8")
    return _read_private(rel)


# 被证伪的表述允许以「撤回台账」的形式留在材料里（这是学术诚信的体现，
# 不是缺陷）。判定标准是它所在的那一行有没有撤回标记。
RETRACT_MARKERS = (
    "包装成",
    "不把",
    "撤回", "不成立", "已删除", "无数据支持", "非拒答", "不是",
    "已更正", "属循环定义", "旧稿", "旧快照", "早期材料", "早期草稿", "曾把",
    "早期版本", "写反", "方向相反", "更正",
)


def _assert_no_unretracted(text, needles, rel, message):
    """被证伪的表述若与撤回标记同处一个段落，则放行；否则视为未标注的继续断言。

    只看单行是不够的：markdown 里一行就是一个整段，撤回说明常写在邻句，
    而 html 又把整页压成一行。所以取「命中行 ±1 行」做窗口判定。
    """
    lines = text.splitlines()
    if isinstance(needles, str):
        needles = (needles,)
    for lineno, line in enumerate(lines, 1):
        if not any(n in line for n in needles):
            continue
        window = " ".join(lines[max(0, lineno - 2):lineno + 1])
        if any(m in window for m in RETRACT_MARKERS):
            continue
        raise AssertionError(f"{rel}:{lineno} {message}：{line.strip()[:200]}")


def test_rag_defense_docs_do_not_quote_single_query_ndcg_as_mrr():
    """0.8171 是单题 nDCG，不得作为方案 MRR 出现在答辩材料里。"""
    for rel in DEFENSE_DOCS:
        _assert_no_unretracted(
            _read_defense(rel),
            ("0.8171",),
            rel,
            "仍把 0.8171 当作 MRR 引用；该值是 detailed_results.hybrid[36] 的"
            "单题 nDCG，不是任何方案的 MRR",
        )


def test_rag_defense_docs_do_not_claim_20x_improvement():
    """20 倍提升的说法已被证伪：与自身旧方案比是 1.00 倍。"""
    for rel in DEFENSE_DOCS:
        text = _read_defense(rel)
        for stale in ("近 20 倍", "近20倍", "提升20倍", "提升 20 倍"):
            _assert_no_unretracted(text, stale, rel, "仍声称检索指标提升 20 倍")


def test_rag_defense_docs_use_measured_mrr_values():
    """答辩材料引用的 MRR 必须能在实验结果的 summary_metrics 里找到。"""
    summary = RAG_RESULTS["summary_metrics"]
    measured = {round(v["MRR"], 4) for v in summary.values()}
    # 英文嵌入基线（all-MiniLM-L6-v2）来自 archive_kb37_268_results.json 的 ablation，
    # 属于另一实验设置，但它是合法读数，允许被引用（必须注明出处）。
    archive = json.loads(
        (ROOT / "docs" / "rag_benchmark" / "archive_kb37_268_results.json").read_text(encoding="utf-8")
    )
    for setting in archive["embedding_ablation"].values():
        for metrics in setting.values():
            measured.add(round(metrics["MRR"], 4))
    # 39 份 / 281 块冻结快照（archive_kb39_281_results.json）是 RQ2 的正式结果口径：
    # 2026-10-25 加入十五五解读后，金标未重标，新库复测只作敏感性参考。
    # 因此该快照里的读数是合法引用的，前提是材料里注明快照来源。
    for snapshot in ("archive_kb39_281_results.json",):
        frozen = json.loads(
            (ROOT / "docs" / "rag_benchmark" / snapshot).read_text(encoding="utf-8")
        )
        for metrics in frozen["summary_metrics"].values():
            measured.add(round(metrics["MRR"], 4))
        for setting in (frozen.get("embedding_ablation") or {}).values():
            for metrics in (setting or {}).values():
                measured.add(round(metrics["MRR"], 4))
    for rel in DEFENSE_DOCS:
        text = _read_defense(rel)
        for token in re.findall(r"MRR[^0-9]{0,12}(0\.\d{4})", text):
            assert float(token) in measured, (
                f"{rel} 引用了实测结果中不存在的 MRR {token}；实测集合为 {sorted(measured)}"
            )


def test_rag_defense_docs_do_not_use_stale_kb_size():
    """旧快照 37 份/268 块不得再作为当前知识库规模出现。"""
    for rel in DEFENSE_DOCS:
        text = _read_defense(rel)
        assert "37 份法规" not in text, f"{rel} 仍使用旧知识库规模 37 份法规"
        assert "37份法规" not in text, f"{rel} 仍使用旧知识库规模 37 份法规"
        assert "268 个 Chunk" not in text and "268 Chunk" not in text, (
            f"{rel} 仍使用旧切片数 268"
        )


def test_defense_docs_do_not_claim_fabricated_vehicle_total():
    """45,035 辆无法由任何车辆子集推出，已被论文更正为覆盖 51,990 辆。"""
    for rel in DEFENSE_DOCS:
        text = _read_defense(rel)
        assert "45,035" not in text, f"{rel} 仍使用无法复算的车辆数 45,035"


def _collected_test_count() -> int:
    """当前真实收集到的测试数，供"文档里的测试数"逐字比对。

    这里刻意**不写死数字**：本测试的文件名就是"口径一致性"，如果它自己把
    "当前真实测试数"抄成常量，那它就成了它要防的东西——历史上 107/119/159/170/173
    都是这样一段段抄旧、再一节节失效的。改为运行时向 pytest 要真实总数。
    """
    global _COLLECTED_CACHE
    if _COLLECTED_CACHE is not None:
        return _COLLECTED_CACHE
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "--ignore=" + str(REPO_ROOT / "tmp")],
        cwd=str(REPO_ROOT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    m = re.search(r"(\d+)\s+tests?\s+collected", proc.stdout)
    if not m:
        pytest.skip("无法取得当前收集数，跳过测试数口径校验")
    _COLLECTED_CACHE = int(m.group(1))
    return _COLLECTED_CACHE


# 历史上出现过 107 / 117 / 119 / 159 / 170 / 173 / 221 / 239 / 258 / 259 等写法。
# 这里只列「显然过期」的旧值；near-current 值（259/260/261/262…）不列入，
# 否则每加一个测试都要回来改这个列表——那正是它要防的「把预期值抄一遍」。
_STALE_TEST_COUNTS = (107, 117, 119, 159, 170, 173, 221, 239)


def _read_any(rel):
    """论文等私有文书不存在时跳过，公开载体不存在时判失败。"""
    return _read_defense(rel) if rel in PUBLIC_DEFENSE_DOCS or rel in DEFENSE_DOCS \
        else _read_private(rel)


def test_test_count_claims_are_not_stale_in_this_paper():
    """论文正文与多份报告仍写「117 项」，而当时实测已是 200+ 项。

    评审指出：这是最容易被现场翻出来的一条——论文是唯一会被逐字读的材料。
    """
    actual = _collected_test_count()
    candidates = [
        "docs/academic_paper.md",
        "docs/中期答辩成果与实证全景报告.md",
        "docs/大创中期进展说明书_技术与实证全景.md",
    ]
    for rel in candidates:
        text = _read_any(rel)
        for stale in _STALE_TEST_COUNTS:
            if stale == actual:
                continue
            for pat in (f"{stale} 项", f"{stale}项"):
                assert pat not in text, (
                    f"{rel} 仍声称「{pat}」测试，当前真实收集数为 {actual}"
                )


def test_defense_docs_test_count_matches_collection():
    """答辩材料写的测试数必须是当前真实收集数，不能是旧值。

    历史上这个数字在仓里出现过 107 / 117 / 119 / 159 / 170 / 173 / 221 七种写法，
    每次都是"文档更新了、守卫没更新"或反之。现在两边都不写死：
    文档必须出现运行时真实收集数，且不得残留任何一个历史旧值。
    """
    actual = _collected_test_count()
    stale_values = [107, 117, 119, 159, 170, 173, 221]
    for rel in DEFENSE_DOCS:
        text = _read_defense(rel)
        for stale in stale_values:
            if stale == actual:
                continue
            for pat in (f"{stale} 项", f"{stale}项"):
                assert pat not in text, (
                    f"{rel} 仍声称「{pat}」测试，当前真实收集数为 {actual}"
                )
        # 只有"陈述测试数"的载体才必须写出当前值：幻灯片生成脚本只负责
        # 逐页渲染，测试数由 html/md 承载，不强求它复述。
        if rel in PUBLIC_DEFENSE_DOCS and rel.endswith(".py"):
            continue
        assert str(actual) in text, (
            f"{rel} 未出现当前真实测试数 {actual}"
        )


# ---------------------------------------------------------------- 车队规模口径

# 覆盖车辆数的历史错写：5.2 万 / 5.3 万 / 4.5 万 / 45,035 都出现过。
VEHICLE_TOTAL_STALE = (
    "5.2 万辆", "5.2万辆", "5.3 万辆", "5.3万辆",
    "4.5 万辆", "4.5万辆", "45,035",
)


def test_public_materials_use_ledger_vehicle_total():
    """对外材料里的车队规模必须与台账 mape.vehicles_total 逐位一致。

    README 曾写「约 5.3 万辆」，答辩 deck 的口播稿写「5.2 万辆台账核对」，
    而台账是 51,990。三个数并存时评委只需问一句「到底几辆」。
    """
    ledger = json.loads((ROOT / "docs" / "derived_metrics.json").read_text(encoding="utf-8"))
    total = ledger["mape"]["vehicles_total"]
    expected = f"{total:,}"
    for rel in ("README.md", "docs/artifacts/defense_presentation_deck.html"):
        text = _read_defense(rel)
        for stale in VEHICLE_TOTAL_STALE:
            assert stale not in text, (
                f"{rel} 仍写「{stale}」；覆盖车辆数应为 {expected}"
            )
        assert expected in text, f"{rel} 未出现正确的覆盖车辆数 {expected}"


def test_public_materials_do_not_claim_refusal_rate():
    """「100% 合规拒答」已被证伪：检索层没有任何拒答实现。

    实测四道负例题的检索命中率是 2/4，即 50%。允许在撤回台账里提到旧说法，
    但不允许作为成果陈述出现。
    """
    for rel in (
        "docs/artifacts/defense_presentation_deck.html",
        "scripts/generate_presentation_pptx.py",
        "README.md",
    ):
        text = _read_defense(rel)
        for needles in (("100% 拒答",), ("100%拒答",), ("拒答率 100",), ("彻底杜绝法律幻觉",)):
            _assert_no_unretracted(text, needles, rel, "仍声称存在 100% 拒答能力")


# ---------------------------------------------------------------- 生成器文本口径

# 旧口径仓库不只在 html 里，更在生成 html/pdf/pptx 的脚本里。只守 html 等于守门不守源。
# build_defense_pdfs.py 的敏感性表与结论段必须从 docs/derived_metrics.json 现算。
# 历史事故：那张 5x5 表原为逐格手抄（+1.22% ~ +7.80%），结论写「满载率是主误差源」，
# 而台账 50 格扫描的真实包络是 3.04%~29.80%，且里程才是主导因子（+20.72~26.76 pp）。
RAG3_HARDCODED_PERCENT = ("+1.22%", "+1.89%", "+2.54%", "+3.20%", "+3.85%",
                          "+2.88%", "+3.60%", "+5.12%", "+5.89%",
                          "+4.38%", "+5.25%", "+6.10%", "+7.01%", "+7.80%",
                          "2.63%", "3.01%")
def _strip_docstrings(text: str) -> str:
    """去掉模块/函数 docstring，只留真正会执行的代码行。

    只剥注释是不够的：docstring 里常写「原先硬编码 +1.22%」这样的历史说明，
    守卫若连它一起命中，就会逼着后来的人删掉有价值的事故记录。
    """
    import re as _re

    pattern = _re.compile(r'(?s)("""|\'\'\').*?\1')
    return pattern.sub("", text)


def _code_lines(text: str) -> str:
    """去掉整行注释，避免守卫命中注释里引用的坏字符串。"""
    kept = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            continue
        kept.append(line)
    return "\n".join(kept)


SENSITIVITY_WRITER = "scripts/build_defense_pdfs.py"
MAIN_SOURCE_CLAIMS = ("满载率是主误差源", "满载率基准假设是主误差源", "满载率是可控主误差源")


def test_defense_pipeline_rq3_table_is_computed_from_ledger():
    code = _strip_docstrings(_code_lines(_read(SENSITIVITY_WRITER)))
    assert "grid_5x5" in code, (
        "敏感性表必须逐格取自台账 sensitivity.grid_5x5，不能手抄"
    )
    hit = [needle for needle in RAG3_HARDCODED_PERCENT if needle in code]
    assert not hit, (
        f"{SENSITIVITY_WRITER} 的代码里仍在手抄敏感性百分比 {hit}；"
        "该表必须从 docs/derived_metrics.json 的 sensitivity.grid_5x5 现算"
    )


def test_defense_pipeline_does_not_blame_load_factor_as_main_source():
    lines = _strip_docstrings(_code_lines(_read(SENSITIVITY_WRITER))).splitlines()
    for index, line in enumerate(lines):
        for needle in MAIN_SOURCE_CLAIMS:
            if needle not in line:
                continue
            # 撤回句常把坏说法放在引号里并在同句或邻句否定，故看前后各两行
            window = "\n".join(lines[max(0, index - 2): index + 3])
            assert any(marker in window for marker in RETRACT_MARKERS), (
                f"{SENSITIVITY_WRITER} 把实载率说成主误差源：{line.strip()[:80]}；"
                "台账实测年均里程才是一阶主导因子（约 5~9 倍）"
            )


GENERATOR_SCRIPTS = (
    "scripts/generate_presentation_pptx.py",
    "scripts/build_defense_pdfs.py",
    "scripts/generate_architecture_svg.py",
    "scripts/package_deliverables.py",
    "scripts/generate_midterm_artifacts.py",
)


def test_generators_do_not_contain_stale_test_counts():
    """生成器里的测试数必须是运行时收集到的数量，不能手写旧值。

    线上真实事故：build_defense_pdfs.py 同一文件里同时写着 106 项与 117 项，
    package_deliverables.py 写 117 项，而实际是 248 项。
    """
    actual = _collected_test_count()
    stale = [
        n for n in (
            105, 106, 107, 117, 119, 159, 170, 173, 220, 221, 239, 241, 247,
            263, 300, 342, 355, 375, 379, 390, 397, 399, 401, 404, 406, 409,
        ) if n != actual
    ]
    for rel in GENERATOR_SCRIPTS:
        text = _read_defense(rel)
        for n in stale:
            for pat in (f"{n} 项", f"{n}项"):
                assert pat not in text, f"{rel} 仍写「{pat}」，实际收集数为 {actual}"


def test_generators_do_not_claim_conservatism_axiom():
    """「保守性公理 / 绝不低估」已被实测证伪（8 条记录中 6 条低估），不得再作结论陈述。"""
    for rel in GENERATOR_SCRIPTS:
        text = _read_defense(rel)
        _assert_no_unretracted(
            text,
            ("保守性公理", "保守估计公理", "绝不低估"),
            rel,
            "仍把已被证伪的「保守性公理/绝不低估」当结论陈述",
        )


def test_generators_do_not_quote_expert_scores():
    """专家评分卡未入库、README 声明不主张任何评分，生成器不得再印分数。"""
    for rel in GENERATOR_SCRIPTS + ("docs/artifacts/defense_presentation_deck.html",):
        text = _read_defense(rel)
        for score in ("4.905", "4.933", "4.877", "4.92 / 5.0", "4.89 / 5.0"):
            if score in text:
                # 允许出现在撤回说明里
                idx = text.find(score)
                window = text[max(0, idx - 120): idx + 120]
                assert "撤回" in window or "此前版本" in window, (
                    f"{rel} 仍把专家评分 {score} 当作成果引用（窗口内无撤回说明）"
                )


def test_deck_does_not_mix_incompatible_baas_paybacks():
    """BaaS 重卡回收期在两套电价下分别是 1.04 年与 1.48 年，不得并列出现而不交代电价口径。

    线上真实事故：Slide 3 结论写 1.04 年、Slide 11 推导写 1.46 年，讲稿还专门
    引导评委追问 1.46，两页并看会当场暴露口径不一致。
    """
    rel = "docs/artifacts/defense_presentation_deck.html"
    text = _read_defense(rel)
    for value in ("1.04", "1.48", "1.46"):
        for m in re.finditer(re.escape(value), text):
            window = text[max(0, m.start() - 400): m.start() + 400]
            assert ("电价" in window) or ("口径" in window) or ("假设" in window), (
                f"{rel} 出现回收期 {value} 年但上下文未交代电价/口径假设"
            )


def test_deck_does_not_call_capex_ratio_a_sensitivity_finding():
    """「降幅 70%」是代数恒等式，不能与敏感性分析并列陈述。"""
    rel = "docs/artifacts/defense_presentation_deck.html"
    text = _read_defense(rel)
    if "69.7%" in text or "降幅 70%" in text:
        assert "代数恒等式" in text, f"{rel} 引用垫资降幅却未声明其为代数恒等式"


# ---------------------------------------------------------------- 4.23% 口径与保守性主张

# 4.23% 是四案例等权 MAPE；按排放量加权是 2.38%。两个数都真实，但不可互换。
WEIGHTED_LABEL_WHITELIST = ("加权 2.38", "加权为 2.38", "按排放量加权 2.38", "加权口径 2.38")


def test_4223_is_not_called_weighted_mape():
    """4.23% 不得被称作「加权 MAPE」。

    线上真实事故：Slide 3 与 PPT 生成器都写「加权 MAPE 4.23%」，
    而按排放量加权其实是 2.38%，等于把一个较小的数披上了较大的名头。
    """
    for rel in GENERATOR_SCRIPTS + ("docs/artifacts/defense_presentation_deck.html",):
        text = _read_defense(rel)
        for m in re.finditer(r"加权[^。；\n]{0,20}4\.23", text):
            window = text[max(0, m.start() - 60): m.start() + 80]
            assert any(w in window for w in WEIGHTED_LABEL_WHITELIST), (
                f"{rel} 把 4.23% 称为「加权 MAPE」，实测加权值为 2.38%：{window!r}"
            )


def test_no_conservatism_padding_claim():
    """「安全垫 / 保守正偏」被 8 条记录中 6 条低估的数据否证，不得作为结论陈述。"""
    for rel in GENERATOR_SCRIPTS + ("docs/artifacts/defense_presentation_deck.html",):
        text = _read_defense(rel)
        _assert_no_unretracted(
            text,
            ("上限安全垫", "安全垫", "恒定正偏", "保守正偏"),
            rel,
            "仍把正偏差包装成「保守性安全垫」",
        )


# ---------------------------------------------------------------- 敏感性网格中位数

MEDIAN_DOCS = (
    "README.md",
    "docs/artifacts/defense_presentation_deck.html",
    "docs/artifacts/all_charts_dashboard.html",
)


def test_sensitivity_median_is_14_51_everywhere():
    """网格中位数实测 14.51；历史上 README/展板/论文分别写过 14.52。"""
    for rel in MEDIAN_DOCS:
        text = _read_defense(rel)
        assert "14.52" not in text, f"{rel} 仍写 14.52%（实测中位数 14.51%）"


# ---------------------------------------------------------------- Kappa 退化

def test_deck_does_not_cite_kappa_as_reliability_evidence():
    """零变异下 κ 恒等于 1，是数学退化，不能援引 Landis & Koch 判据论证客观性。

    线上真实事故：展板 Slide 8 原文写「Kappa = 1.00 属于最高等级的『完全一致
    (Almost Perfect Agreement)』，证明本评测金标集具备严谨学术客观性」，
    而同一批材料的生成器与论文都已声明 Kappa 不作信度证据。
    """
    rel = "docs/artifacts/defense_presentation_deck.html"
    text = _read_defense(rel)
    assert "Almost Perfect" not in text, f"{rel} 仍把 κ=1 描述为「完全一致」"
    assert "证明本评测金标集" not in text, f"{rel} 仍用 κ=1 论证金标集客观性"
    # 必须留下退化说明
    assert "数学退化" in text or "零变异" in text, f"{rel} 缺少 κ 退化的说明"


# ---------------------------------------------------------------- 插件端点存在性

PLUGIN_INDEX = "packages/dsh-plugin-carbon-asset/src/index.ts"


def _plugin_pairs():
    """从插件源码里抽出 (HTTP 端点, CLI 命令) 对。"""
    src = _read(PLUGIN_INDEX)
    return re.findall(r"bridge\.execute\('(/api[^']+)',\s*'([a-z-]+)'", src)


def test_plugin_endpoints_are_registered_or_known_missing():
    """/api/turnover 未实现，必须被显式登记为缺口，而不是悄悄留在插件里。"""
    pairs = _plugin_pairs()
    assert pairs, "无法从插件源码解析出 bridge.execute 调用"

    known_gaps = Path("docs/known_gaps.md")
    gap_text = known_gaps.read_text(encoding="utf-8") if known_gaps.exists() else ""

    missing = []
    for endpoint, _command in pairs:
        if endpoint == "/api/turnover":
            missing.append(endpoint)
    for endpoint in missing:
        assert endpoint in gap_text, (
            f"插件调用了未实现的 {endpoint}，但 docs/known_gaps.md 未登记该缺口"
        )


def test_plugin_does_not_claim_mcp_support():
    """本项目只交付 DeepSeek Harness 插件，未实现 MCP server，材料不得混称。"""
    src = _read(PLUGIN_INDEX)
    assert "MCP" not in src and "mcp_server" not in src
    readme = _read("README.md")
    for m in re.finditer(r"MCP", readme):
        window = readme[max(0, m.start() - 120): m.start() + 200]
        assert ("未实现" in window) or ("不是" in window) or ("没有" in window), (
            f"README 提到 MCP 但未说明本项目未实现：{window!r}"
        )

# 「专家双盲评审 / 4.905 分」是本项目被反复点名的问题：README 已声明不主张任何
# 专家评分，评分卡原件也未纳入公开仓库，但答辩材料与生成器里仍把它当卖点。
# 这里把规则写成守卫，避免下一次又漂回去。
EXPERT_SCORE_NEEDLES = ("4.905", "4.933", "4.877")
EXPERT_SCORE_FILES = (
    "docs/artifacts/defense_presentation_deck.html",
    "scripts/build_defense_pdfs.py",
    "scripts/generate_presentation_pptx.py",
    "docs/中期答辩成果与实证全景报告.md",
    "docs/大创中期答辩核心指南与评审问辨应对.md",
    "docs/国家级优秀大创答辩逐字稿与尖锐质询策略_升级版.md",
    "docs/大创中期答辩幻灯片视觉与内容全景设计图解.md",
)


def test_expert_scores_are_never_used_as_evidence():
    """任何材料提到 4.905 等分数时，同段落必须同时说明「不主张/已撤回/未署名」。"""
    for rel in EXPERT_SCORE_FILES:
        text = _read_defense(rel)
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if not any(needle in line for needle in EXPERT_SCORE_NEEDLES):
                continue
            window = "\n".join(lines[max(0, index - 3) : index + 4])
            assert any(
                marker in window
                for marker in ("不主张", "已撤回", "未署名", "不引用", "不作证据", "撤回")
            ), f"{rel}:{index + 1} 引用了专家评分却没有说明不可核验/不主张：{line.strip()[:80]}"


def test_defense_materials_do_not_claim_double_blind_expert_review():
    """专家意见是「非结构化咨询访谈」，不能写成「双盲同行评议」。"""
    for rel in EXPERT_SCORE_FILES:
        text = _read_defense(rel)
        lines = text.splitlines()
        for index, line in enumerate(lines):
            if "双盲" not in line:
                continue
            window = "\n".join(lines[max(0, index - 2) : index + 3])
            assert any(
                marker in window
                for marker in ("非双盲", "不是双盲", "不构成", "单盲", "不使用")
            ), f"{rel}:{index + 1} 把专家意见写成双盲评审：{line.strip()[:80]}"


LEDGER_PATH_FOR_GRID = "docs/derived_metrics.json"


def _grid_heavy():
    import json

    return json.loads(_read(LEDGER_PATH_FOR_GRID))["grid"]["heavy"]


def test_reversal_province_count_is_not_reported_as_a_single_fixed_number():
    """「N 个省份重卡碳排放反超柴油车」必须同时给出两套电耗口径下的数。

    同一个量随一个未声明的假设翻倍（140 kWh 下 6 个、150 kWh 下 10 个），
    只报一个数就是把假设当结论。
    """
    heavy = _grid_heavy()
    main_kwh = heavy["kwh_per_100km_main"]
    alt_kwh = heavy["kwh_per_100km_alt"]
    assert main_kwh == 140.0, "主口径必须与 TCO 基准一致（140 kWh/100km）"
    assert alt_kwh == 150.0, "150 kWh/100km 应作为敏感性对照保留"
    assert heavy["n_regions_negative_main"] == 6
    assert heavy["n_regions_negative_alt"] == 10
    assert len(heavy["regions_negative_at_alt_kwh"]) == 10
    assert len(heavy["regions_above_threshold"]) == 6
    alt = heavy["heavy_net_pct_at_alt_kwh"]
    assert alt["天津"] < alt["陕西"], "150 kWh 口径下天津应比陕西更负"


def test_deliverables_do_not_quote_the_reversal_count_without_the_assumption():
    text = _read("scripts/package_deliverables.py")
    assert "140 kWh" in text and "150 kWh" in text, (
        "对外说明必须同时给出 140 与 150 两套电耗口径"
    )
    for line in text.splitlines():
        if "反超" not in line:
            continue
        assert "140 kWh" in line or "150 kWh" in line, (
            f"提及「反超」的行必须同时交代电耗口径：{line.strip()[:80]}"
        )
