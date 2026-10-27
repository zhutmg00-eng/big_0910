"""评测报告生成不得吃掉手工追加的附录。

背景（真实缺陷，实测于 2026-10-27）：
`scripts/evaluate_rag_benchmark.py` 的 `write_markdown_report` 用整文件覆写方式
生成 `rag_retrieval_experiment_report.md`，而该报告的「附录 C」是人工撰写的
39 份/281 块 → 40 份/287 块复测对照（含金标过期原因分析），不是脚本产物。
任何人重跑一次评测，这段结论就静默消失——而当时的复测结论恰好要用它解释
MRR 为何从 0.4920 降到 0.4782，丢掉之后报告会自相矛盾。

修复后：生成段只写到「五、结论与局限」，`\\n---\\n\\n## 附录` 之后的正文原样续接。
本文件用临时目录实跑一次，锁死该行为。
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "evaluate_rag_benchmark", ROOT / "scripts" / "evaluate_rag_benchmark.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _payload() -> dict:
    return {
        "benchmark_metadata": {
            "total_documents": 40,
            "total_chunks": 287,
            "embedding_model": "fastembed:BAAI/bge-small-zh-v1.5",
            "rrf_weights": {"bm25": 0.6, "vector": 0.1, "keyword": 0.8},
            "bootstrap_resamples": 2000,
            "multiple_comparison": "Holm-Bonferroni",
        },
        "summary_metrics": {
            m: {
                "MRR": 0.4,
                "MRR_CI95": [0.3, 0.5],
                "nDCG@10": 0.4,
                "Recall@1": 0.3,
                "Recall@3": 0.4,
                "Recall@5": 0.5,
                "Recall@10": 0.6,
                "Source_Hit@5": 0.8,
                "Negative_Rejection_Accuracy": 0.5,
            }
            for m in ("keyword", "vector", "hybrid", "bm25", "rrf", "rrf3")
        },
        "statistical_significance": {
            "rrf3_vs_vector": {
                "W_stat": 10.0, "p_value": 0.01, "p_holm": 0.02, "is_significant_005": True,
            }
        },
        "embedding_ablation": None,
    }


APPENDIX = """

---

## 附录 C：加入《绿色交通发展“十五五”规划》官方解读后的复测（2026-10-25）

- 这段是人工撰写的内容，重跑脚本不得删除。
"""


@pytest.fixture
def isolated_report(tmp_path, monkeypatch):
    """把脚本的输出路径指到临时目录，避免测试改动仓库里的正式报告。"""
    module = _load_module()
    out_md = tmp_path / "report.md"
    out_json = tmp_path / "results.json"
    monkeypatch.setattr(module, "OUT_MD", out_md)
    monkeypatch.setattr(module, "OUT_JSON", out_json)
    return module, out_md


def test_appendix_survives_regeneration(isolated_report):
    module, out_md = isolated_report
    out_md.write_text("# 旧报告\n\n正文\n" + APPENDIX, encoding="utf-8")

    module.write_markdown_report(_payload())

    text = out_md.read_text(encoding="utf-8")
    assert "附录 C" in text, "重跑报告把人工附录吃掉了"
    assert "这段是人工撰写的内容，重跑脚本不得删除" in text
    # 同时确认生成段确实被刷新，而不是整份文件原样保留
    assert "RAG 政策问答检索对照实验报告" in text


def test_no_appendix_means_clean_regeneration(isolated_report):
    module, out_md = isolated_report
    out_md.write_text("# 旧报告\n\n没有附录。\n", encoding="utf-8")

    module.write_markdown_report(_payload())

    text = out_md.read_text(encoding="utf-8")
    assert "没有附录。" not in text, "无附录时旧正文应被完整替换"
    assert "RAG 政策问答检索对照实验报告" in text


def test_report_is_byte_stable_across_two_runs(isolated_report):
    """同一份 payload 连跑两次，第二次不得因为残留说明而变化。"""
    module, out_md = isolated_report
    module.write_markdown_report(_payload())
    first = out_md.read_text(encoding="utf-8")
    module.write_markdown_report(_payload())
    assert out_md.read_text(encoding="utf-8") == first


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
