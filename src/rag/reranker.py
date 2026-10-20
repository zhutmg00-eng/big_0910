"""可选的交叉编码器（Cross-Encoder）精排。

两阶段检索的第二阶段：对 RRF 融合后的前 N 个候选，用交叉编码器逐对计算
(query, passage) 相关性后重新排序。交叉编码器能同时“看到”问题和段落，
精度显著高于双塔向量，但 CPU 上较慢，因此默认关闭。

启用方式：设置环境变量 ``RERANKER_MODEL=BAAI/bge-reranker-base``
（或 ``BAAI/bge-reranker-v2-m3-int8``），并安装 fastembed。
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import Dict, List

from src.config import MODEL_CACHE_DIR

DEFAULT_RERANKER = "BAAI/bge-reranker-base"
RERANKER_MODEL = os.getenv("RERANKER_MODEL", "").strip()
RERANK_CANDIDATES = int(os.getenv("RERANK_CANDIDATES") or 20)
RERANK_MAX_CHARS = int(os.getenv("RERANK_MAX_CHARS") or 400)


@lru_cache(maxsize=2)
def get_reranker(model_name: str):
    from fastembed.rerank.cross_encoder import TextCrossEncoder

    return TextCrossEncoder(model_name=model_name, cache_dir=str(MODEL_CACHE_DIR))


def _passage(text: str) -> str:
    # 保留“来源文档：xxx”标题行 + 正文前若干字，控制 CPU 推理耗时
    return text[:RERANK_MAX_CHARS]


def rerank(query: str, items: List[Dict], model_name: str | None = None, top_k: int | None = None) -> List[Dict]:
    model_name = model_name or RERANKER_MODEL
    if not model_name or not items:
        return items[:top_k] if top_k else items
    model = get_reranker(model_name)
    scores = list(model.rerank(query, [_passage(it.get("text", "")) for it in items]))
    ranked = sorted(zip(items, scores), key=lambda x: x[1], reverse=True)
    out = []
    for it, s in ranked:
        it = dict(it)
        it["rerank_score"] = float(s)
        it["retrievers"] = list(it.get("retrievers", [])) + ["rerank"]
        out.append(it)
    return out[:top_k] if top_k else out
