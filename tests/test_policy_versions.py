"""十四五 / 十五五 绿色交通规划并列收录，且版本关系写明（2026-10-25）。"""
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "data" / "policy_docs"
OLD = DOCS / "绿色交通十四五发展规划.md"
NEW = DOCS / "绿色交通发展十五五规划_官方解读_2026.md"


def test_both_plans_present_and_linked():
    old, new = OLD.read_text(encoding="utf-8"), NEW.read_text(encoding="utf-8")
    assert "版本状态" in old and "十五五" in old, "十四五版须注明已被接续"
    assert "新版" in new and "十四五" in new, "十五五版须注明为新版并指向旧版"


def test_new_plan_keeps_source_wording():
    new = NEW.read_text(encoding="utf-8")
    for phrase in ("一达峰、二下降、三提升", "全面淘汰国三及以下排放标准营运车辆", "新能源重卡规模化应用"):
        assert phrase in new
    assert "官方解读" in new and "以规划正文为准" in new, "正文未公开，必须标明收录的是解读"
