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
    "撤回", "不成立", "已删除", "无数据支持", "非拒答", "不是",
    "已更正", "属循环定义", "旧稿", "旧快照", "早期材料", "早期草稿", "曾把",
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
