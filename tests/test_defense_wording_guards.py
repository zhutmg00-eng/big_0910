"""答辩载体措辞守卫（2026-10-25 补充）。

test_claim_consistency.py 只拦「双盲评审」「4.905」这类原词，下面这些变体曾漏网：
- 「专家盲评」：专家意见只是非结构化咨询访谈，且访谈原件尚待补签，不能称「盲评」；
- PPTX 生成器与交付清单里的旧中位数 14.52（台账实测 14.51）；
- 「降幅 70%！」：69.7% 是车电分离架构下的代数恒等式，不是优化或敏感性结论；
- 「GHG Protocol 保守性方向」：保守性主张已被实测证伪并撤回；
- 「51,990 辆台账核对」：51,990 辆是 4 家企业披露的覆盖车辆数，项目没有逐车台账；
- 「N 项全绿」：公开仓库必有跳过项（私有文书、真实 API Key），展板测试数必须由脚本按实测回写。
"""
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

DEFENSE_CARRIERS = (
    "docs/artifacts/defense_presentation_deck.html",
    "scripts/build_defense_pdfs.py",
    "scripts/generate_presentation_pptx.py",
    "scripts/package_deliverables.py",
    "README.md",
)


def _text(rel: str) -> str:
    path = ROOT / rel
    assert path.exists(), f"{rel} 是公开答辩载体，必须在仓库中"
    return path.read_text(encoding="utf-8")


def _windows(text: str, needle: str, radius: int = 60):
    for m in re.finditer(re.escape(needle), text):
        yield text[max(0, m.start() - radius): m.end() + radius]


def test_no_blind_review_wording():
    """「盲评」只能出现在否定语境里（非双盲、不构成双盲……）。"""
    for rel in DEFENSE_CARRIERS:
        text = _text(rel)
        for w in _windows(text, "盲评", radius=12):
            assert any(neg in w for neg in ("非双盲", "非盲", "不是双盲", "不构成", "并非")), (
                f"{rel} 仍把专家意见写成「盲评」：{w!r}"
            )


def test_sensitivity_median_matches_ledger():
    ledger = json.loads(_text("docs/derived_metrics.json"))
    median = f'{ledger["sensitivity"]["median_pct"]:.2f}'
    for rel in DEFENSE_CARRIERS:
        for value in re.findall(r"中位数\s*(?:为\s*)?(\d+\.\d+)\s*%", _text(rel)):
            if float(value) > 10:  # 只核对网格误差中位数（其余中位数量级不同）
                assert value == median, f"{rel} 写网格中位数 {value}%，台账为 {median}%"


def test_capex_ratio_is_not_rounded_or_oversold():
    for rel in DEFENSE_CARRIERS:
        text = _text(rel)
        assert "降幅 70%" not in text and "降幅70%" not in text, f"{rel} 仍写「降幅 70%」"
    for rel in ("scripts/generate_presentation_pptx.py", "docs/artifacts/defense_presentation_deck.html"):
        text = _text(rel)
        for w in _windows(text, "69.7%", radius=160):
            assert "代数恒等" in w, f"{rel} 引用 69.7% 但附近未声明是代数恒等式：{w[100:220]!r}"


def test_no_retracted_conservatism_or_ledger_overclaim():
    banned = ("GHG Protocol 保守性", "保守性方向", "台账核对", "逐车台账核对")
    for rel in DEFENSE_CARRIERS:
        text = _text(rel)
        for phrase in banned:
            assert phrase not in text, f"{rel} 仍含已撤回/夸大表述「{phrase}」"


def test_no_all_green_claims():
    for rel in DEFENSE_CARRIERS:
        assert "全绿" not in _text(rel), f"{rel} 仍写「全绿」，公开仓库必有跳过项"


def test_deck_test_counts_are_script_synced():
    """展板里所有「N 项…测试」都必须是 data-test-count 标记，且三个数自洽。"""
    text = _text("docs/artifacts/defense_presentation_deck.html")
    stripped = re.sub(r'<span data-test-count="\w+">\d+</span>', "#", text)
    hard = re.findall(r"\d{3}\s*项[^<。；]{0,10}测试", stripped)
    assert not hard, f"展板仍有手写测试数：{hard}（请改用 data-test-count 标记）"
    spans = re.findall(r'<span data-test-count="(\w+)">(\d+)</span>', text)
    assert spans, "展板缺少 data-test-count 标记"
    vals = {}
    for kind, n in spans:
        vals.setdefault(kind, set()).add(int(n))
    for kind, s in vals.items():
        assert len(s) == 1, f"展板 {kind} 测试数前后不一致：{sorted(s)}"
    if {"collected", "passed", "skipped"} <= vals.keys():
        c, p, s = (next(iter(vals[k])) for k in ("collected", "passed", "skipped"))
        assert c == p + s, f"展板测试数不自洽：{c} ≠ {p} + {s}"
