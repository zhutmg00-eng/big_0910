"""政策知识库：ChromaDB 稠密检索 + 中文 BM25 + RRF 融合。

``_lexical_relevance`` 为 v0.3 的字面启发式打分，现仅用于 ``keyword`` /
``hybrid`` / ``rrf3`` 对照模式，便于在评测报告中做消融分析。
"""
from __future__ import annotations

import hashlib
import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Optional

from src.config import (
    CHROMA_DB_DIR, EMBEDDING_MODEL, RETRIEVAL_MODE, RRF_CANDIDATES, RRF_K, RRF_WEIGHTS,
)
from src.rag.bm25 import BM25Index, reciprocal_rank_fusion
from src.rag.embeddings import get_embedder, resolve_embedding_setting
from src.rag.reranker import DEFAULT_RERANKER, RERANK_CANDIDATES, RERANKER_MODEL, rerank

logger = logging.getLogger(__name__)

# 尝试导入chromadb
try:
    import chromadb
    CHROMA_AVAILABLE = True
except ImportError:
    CHROMA_AVAILABLE = False


def _char_ngrams(text: str, n: int = 2) -> set[str]:
    compact = re.sub(r"[^0-9A-Za-z\u4e00-\u9fff]+", "", text.lower())
    if len(compact) < n:
        return {compact} if compact else set()
    return {compact[i:i + n] for i in range(len(compact) - n + 1)}


def _lexical_relevance(query: str, text: str, source: str = "") -> float:
    """计算适合中文政策标题和正文的轻量关键词覆盖率。"""
    query_grams = _char_ngrams(query, 2) | _char_ngrams(query, 3)
    if not query_grams:
        return 0.0

    text_grams = _char_ngrams(text, 2) | _char_ngrams(text, 3)
    source_grams = _char_ngrams(source, 2) | _char_ngrams(source, 3)
    content_coverage = len(query_grams & text_grams) / len(query_grams)
    source_coverage = len(query_grams & source_grams) / len(query_grams)

    domain_terms = [
        "物流", "运输", "公路", "水路", "碳排放", "核算", "报告",
        "碳达峰", "目标", "配额", "履约", "碳交易", "自愿减排", "ccer",
        "货车", "车辆", "车队", "燃油", "新能源", "减排", "满载率",
        "试点", "北京", "上海", "广东", "清缴", "豁免", "基准",
    ]
    matched_terms = [term for term in domain_terms if term in query.lower()]
    combined = f"{source}\n{text}".lower()
    term_coverage = (
        sum(term in combined for term in matched_terms) / len(matched_terms)
        if matched_terms else 0.0
    )
    score = 0.40 * content_coverage + 0.40 * source_coverage + 0.20 * term_coverage

    q_lower = query.lower()
    # 针对政策主题细分维度的针对性重排匹配
    if any(k in q_lower for k in ["ccer", "自愿减排", "额外性"]):
        if any(k in source for k in ["自愿减排", "CCER", "建设意见", "吹风会"]):
            score += 0.20
    if any(k in q_lower for k in ["试点", "北京", "上海", "广东"]):
        if any(k in source for k in ["北京", "上海", "广东"]):
            score += 0.20
    if any(k in q_lower for k in ["配额", "清缴", "豁免", "基准线", "分配方案"]):
        if any(k in source for k in ["配额", "分配方案"]):
            score += 0.15
    if any(k in q_lower for k in ["核查", "数据质量", "检验检测", "保守性"]):
        if any(k in source for k in ["核查", "指南"]):
            score += 0.15
    if any(k in q_lower for k in ["gb", "30510", "限值", "油耗", "商用车辆"]):
        if "30510" in source:
            score += 0.25

    vehicle_query = any(term in query for term in ("物流", "运输", "货车", "车辆", "车队", "燃油"))
    transport_source = any(term in source for term in ("交通", "运输", "公路", "水路", "车辆"))
    is_specific_trading_q = any(term in q_lower for term in ("碳交易", "配额", "履约", "ccer", "自愿减排", "试点"))
    if vehicle_query and transport_source and not is_specific_trading_q:
        score += 0.15
    return min(1.0, score)


class PolicyVectorStore:
    """碳交易 / 交通低碳政策知识库。

    检索架构（v0.4）::

        query ──┬── BM25 (jieba 分词)            ──┐
                ├── 稠密向量 (bge-small-zh, ONNX)  ──┼── RRF 倒数排名融合 ── Top-K
                └── (可选) 旧版字面启发式打分      ──┘

    - ``mode="rrf"``（默认）：BM25 + 稠密向量 RRF 融合，无需在评测集上调权重；
    - ``mode="rrf3"``：在 rrf 基础上再融合旧版字面启发式，作为消融对照；
    - ``mode="rerank"``：rrf3 召回前 N 个候选后，用交叉编码器 (bge-reranker) 精排；
      另外只要设置了环境变量 RERANKER_MODEL，rrf / rrf3 也会自动追加精排；
    - ``mode="hybrid"``：v0.3 旧版“向量 0.35 + 启发式 0.65”加权重排，保留以便复现；
    - ``mode="bm25" | "vector" | "keyword"``：单路检索基线。

    ChromaDB 未安装时自动降级为纯 BM25 + JSON 持久化。
    """

    MODES = ("rrf", "rrf3", "rerank", "hybrid", "bm25", "vector", "keyword")

    def __init__(self, persist_dir: str = None, embedding_model: str | None = None):
        self.persist_dir = persist_dir or str(CHROMA_DB_DIR)
        self.embedding_model = resolve_embedding_setting(embedding_model or EMBEDDING_MODEL)
        model_id = hashlib.sha1(self.embedding_model.encode("utf-8")).hexdigest()[:8]
        self.collection_name = f"carbon_policy_v5_{model_id}"
        self.fallback_cache_file = (
            Path(self.persist_dir) / f"{self.collection_name}_fallback_docs.json"
        )
        self._fallback_docs: List[Dict] = []
        self._bm25 = None
        self._bm25_signature = None
        self._corpus_cache: Optional[Dict] = None
        self._embedder = None

        self._chroma_ok = CHROMA_AVAILABLE
        self._degrade_reason = "" if self._chroma_ok else "chromadb 未安装"
        if self._chroma_ok:
            try:
                self._init_chroma()
            except Exception as exc:  # 磁盘损坏 / 锁 / 版本不兼容 → 自动降级
                logger.warning("ChromaDB 初始化失败，降级为 BM25：%s", exc)
                self._chroma_ok = False
                self._degrade_reason = f"ChromaDB 初始化失败：{type(exc).__name__}"
        if not self._chroma_ok:
            self._init_fallback()

    # ------------------------------------------------------------------ 初始化
    @property
    def embedder(self):
        if self._embedder is None:
            self._embedder = get_embedder(self.embedding_model)
        return self._embedder

    def _init_chroma(self):
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        self.collection = self.client.get_or_create_collection(
            name=self.collection_name,
            embedding_function=None,
            metadata={
                "description": "中国碳交易与交通低碳政策知识库",
                "embedding_model": self.embedding_model,
                "hnsw:space": "cosine",
            },
        )
        logger.info("ChromaDB 知识库 %s: %d 个文档块", self.collection_name, self.collection.count())

    def _init_fallback(self):
        import json
        if self.fallback_cache_file.exists():
            self._fallback_docs = json.loads(self.fallback_cache_file.read_text(encoding="utf-8"))

    # ------------------------------------------------------------------ 入库
    def add_documents(self, chunks: List[Dict], doc_source: str, doc_date: str = ""):
        """向知识库添加文档 chunk（同名文档整体替换，保证幂等）。"""
        if not chunks:
            return
        if self._chroma_ok:
            self._add_chroma(chunks, doc_source, doc_date)
        else:
            self._add_fallback(chunks, doc_source, doc_date)
        self._invalidate_caches()

    def _add_chroma(self, chunks: List[Dict], doc_source: str, doc_date: str = ""):
        # 先删除该文档旧的 chunk，避免文档变短后残留“幽灵块”
        try:
            self.collection.delete(where={"source": doc_source})
        except Exception:  # pragma: no cover
            pass
        ids, documents, metadatas = [], [], []
        for i, chunk in enumerate(chunks):
            ids.append(f"{doc_source}_{i}")
            documents.append(f"来源文档：{doc_source}\n{chunk['text']}")
            metadatas.append({
                "source": doc_source,
                "date": doc_date,
                "chunk_index": i,
                **chunk.get("metadata", {}),
            })
        embeddings = self.embedder.embed_documents(documents)
        self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas, embeddings=embeddings)
        logger.info("已入库 %d 个文档块: %s", len(chunks), doc_source)

    def _add_fallback(self, chunks: List[Dict], doc_source: str, doc_date: str = ""):
        import json
        self._fallback_docs = [
            d for d in self._fallback_docs if d.get("metadata", {}).get("source") != doc_source
        ]
        for i, chunk in enumerate(chunks):
            self._fallback_docs.append({
                "id": f"{doc_source}_{i}",
                "text": f"来源文档：{doc_source}\n{chunk['text']}",
                "metadata": {"source": doc_source, "date": doc_date, "chunk_index": i,
                             **chunk.get("metadata", {})},
            })
        self.fallback_cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.fallback_cache_file.write_text(
            json.dumps(self._fallback_docs, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    # ------------------------------------------------------------------ 语料缓存
    def _invalidate_caches(self):
        self._bm25 = None
        self._bm25_signature = None
        self._corpus_cache = None

    def count(self) -> int:
        return self.collection.count() if self._chroma_ok else len(self._fallback_docs)

    def _corpus(self) -> Dict:
        """全量语料（id → text/metadata），按文档块数量做简单失效判断。"""
        n = self.count()
        if self._corpus_cache is not None and self._corpus_cache["n"] == n:
            return self._corpus_cache
        if self._chroma_ok:
            got = self.collection.get(include=["documents", "metadatas"])
            ids, docs, metas = got["ids"], got["documents"], got["metadatas"]
        else:
            ids = [d["id"] for d in self._fallback_docs]
            docs = [d["text"] for d in self._fallback_docs]
            metas = [d.get("metadata", {}) for d in self._fallback_docs]
        self._corpus_cache = {
            "n": n,
            "ids": ids,
            "by_id": {i: (t, m or {}) for i, t, m in zip(ids, docs, metas)},
        }
        return self._corpus_cache

    def _bm25_index(self) -> BM25Index:
        corpus = self._corpus()
        if self._bm25 is None or self._bm25_signature != corpus["n"]:
            texts = [corpus["by_id"][i][0] for i in corpus["ids"]]
            self._bm25 = BM25Index(corpus["ids"], texts)
            self._bm25_signature = corpus["n"]
        return self._bm25

    def _item(self, chunk_id: str, distance: float, **extra) -> Dict:
        text, meta = self._corpus()["by_id"].get(chunk_id, ("", {}))
        return {"id": chunk_id, "text": text, "metadata": meta, "distance": float(distance), **extra}

    # ------------------------------------------------------------------ 单路检索器
    def _rank_bm25(self, query: str, k: int) -> List[tuple[str, float]]:
        index = self._bm25_index()
        return [(index.ids[i], s) for i, s in index.top_k(query, k)]

    def _rank_vector(self, query: str, k: int) -> List[tuple[str, float]]:
        if not self._chroma_ok:
            return []
        total = self.collection.count()
        if total == 0:
            return []
        try:
            qvec = self.embedder.embed_query(query)
        except Exception as exc:  # 嵌入模型缺失/下载失败：本次查询退化为词法检索
            logger.warning("向量检索不可用，本次跳过向量路：%s", exc)
            self._degrade_reason = f"嵌入模型不可用：{type(exc).__name__}"
            return []
        res = self.collection.query(
            query_embeddings=[qvec],
            n_results=min(total, k),
            include=["distances"],
        )
        return list(zip(res["ids"][0], map(float, res["distances"][0])))

    def _rank_lexical(self, query: str, k: int) -> List[tuple[str, float]]:
        corpus = self._corpus()
        scored = [
            (cid, _lexical_relevance(query, corpus["by_id"][cid][0],
                                     corpus["by_id"][cid][1].get("source", "")))
            for cid in corpus["ids"]
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    # ------------------------------------------------------------------ 对外检索接口
    def search(self, query: str, k: int = 5, mode: str | None = None) -> List[Dict]:
        """检索最相关的政策条款。返回 [{id, text, metadata, distance, score, retrievers}]。"""
        mode = (mode or RETRIEVAL_MODE).lower()
        if mode not in self.MODES:
            raise ValueError(f"未知检索模式 {mode}，可选 {self.MODES}")
        if self.count() == 0:
            return []
        if not self._chroma_ok and mode in {"vector", "hybrid", "rrf", "rrf3"}:
            mode = "bm25"

        if mode == "bm25":
            ranked = self._rank_bm25(query, k)
            top = ranked[0][1] if ranked else 1.0
            return [self._item(cid, 1 - s / (top or 1), score=s, retrievers=["bm25"]) for cid, s in ranked]
        if mode == "vector":
            return [self._item(cid, d, score=1 - d, retrievers=["vector"])
                    for cid, d in self._rank_vector(query, k)]
        if mode == "keyword":
            return [self._item(cid, 1 - s, score=s, retrievers=["keyword"])
                    for cid, s in self._rank_lexical(query, k)]
        if mode == "hybrid":
            return self._search_legacy_hybrid(query, k)
        if mode == "rerank" or (RERANKER_MODEL and mode in {"rrf", "rrf3"}):
            base = "rrf3" if mode == "rerank" else mode
            candidates = self._search_fused(query, max(k, RERANK_CANDIDATES), base)
            return rerank(query, candidates, model_name=RERANKER_MODEL or DEFAULT_RERANKER, top_k=k)
        return self._search_fused(query, k, mode)

    def _search_fused(self, query: str, k: int, mode: str) -> List[Dict]:

        n = max(RRF_CANDIDATES, k)
        rankings = {
            "bm25": [cid for cid, _ in self._rank_bm25(query, n)],
            "vector": [cid for cid, _ in self._rank_vector(query, n)],
        }
        if mode == "rrf3":
            rankings["keyword"] = [cid for cid, _ in self._rank_lexical(query, n)]
        weights = [RRF_WEIGHTS.get(name, 1.0) for name in rankings]
        fused = reciprocal_rank_fusion(list(rankings.values()), k=RRF_K, weights=weights)[:k]
        max_possible = sum(weights) / (RRF_K + 1)
        results = []
        for cid, score in fused:
            hit_by = [name for name, r in rankings.items() if cid in r[:n]]
            # distance 归一化到 [0,1]：被所有检索器排第一时为 0
            results.append(self._item(cid, 1 - score / max_possible, score=score, retrievers=hit_by))
        return results

    def _search_legacy_hybrid(self, query: str, k: int) -> List[Dict]:
        """v0.3 旧版：向量召回后按 0.35×语义 + 0.65×启发式字面分 重排（仅供复现对照）。"""
        corpus = self._corpus()
        candidates = self._rank_vector(query, min(len(corpus["ids"]), max(k * 50, 500)))
        out = []
        for cid, dist in candidates:
            text, meta = corpus["by_id"][cid]
            semantic = 1.0 / (1.0 + max(dist, 0.0))
            lexical = _lexical_relevance(query, text, meta.get("source", ""))
            combined = 0.35 * semantic + 0.65 * lexical
            out.append(self._item(cid, 1 - combined, score=combined, retrievers=["vector", "keyword"]))
        out.sort(key=lambda x: x["distance"])
        return out[:k]

    # 兼容旧接口
    def search_vector_only(self, query: str, k: int = 5) -> List[Dict]:
        return self.search(query, k, mode="vector")

    def search_keyword_only(self, query: str, k: int = 5) -> List[Dict]:
        return self.search(query, k, mode="keyword")

    # ------------------------------------------------------------------ 统计与维护
    def get_stats(self) -> dict:
        corpus = self._corpus() if self.count() else {"by_id": {}}
        sources = {m.get("source", "") for _, m in corpus["by_id"].values()}
        return {
            "total_chunks": self.count(),
            "total_documents": len(sources),
            "collection_name": self.collection_name,
            "mode": "chromadb" if self._chroma_ok else "bm25_fallback",
            "embedding_model": self.embedding_model if self._chroma_ok else "none",
            "retrieval_mode": RETRIEVAL_MODE,
            "degrade_reason": self._degrade_reason,
        }

    def health(self) -> Dict:
        """知识库健康自检：把"看起来能跑但其实是空的"这类静默故障显式化。

        历史故障（2026-10 实测）：collection 名由嵌入模型哈希派生
        （``carbon_policy_v5_<md5(model)[:8]>``），因此只要换嵌入模型
        （例如从 chromadb-default 换到 bge-small-zh），
        ``get_or_create_collection`` 就会**新建一个空 collection**，
        旧的 268/281 块 collection 仍留在磁盘上但不再被读到——
        政策问答从此返回空结果，而日志里没有任何报错。
        本地 data/chroma_db/chroma.sqlite3 里能查到 5 个历史 collection
        （v2/v3 各 57 块、v4 268 块、v5_3029251b 281 块、v5_a7d89e68 281 块，
        其中 57 块那份是只有 9 份文档的早期残缺库）。

        Returns:
            dict，字段含 status（ok/empty/stale）、count、documents、
            embedding_model、collection_name、other_collections（同库其它
            collection 名 → 块数）、warning（需要人看的提示，无则空串）。
        """
        count = self.count()
        sources = self.source_hashes() if count else {}
        out = {
            "status": "ok",
            "count": count,
            "documents": len(sources),
            "embedding_model": self.embedding_model,
            "collection_name": self.collection_name,
            "other_collections": {},
            "warning": "",
        }
        if not self._chroma_ok:
            out["status"] = "degraded"
            out["warning"] = f"ChromaDB 不可用（{self._degrade_reason}），当前检索依赖 BM25 缓存。"
            return out

        # 同库其它 collection：用于提示"你的语料在另一份 collection 里"
        others: Dict[str, int] = {}
        try:
            for col in self.client.list_collections():
                name = col if isinstance(col, str) else getattr(col, "name", str(col))
                if name == self.collection_name:
                    continue
                try:
                    others[name] = self.client.get_collection(name).count()
                except Exception:  # pragma: no cover - 单份损坏不应影响整体自检
                    others[name] = -1
        except Exception as exc:  # pragma: no cover
            logger.debug("列举 collection 失败：%s", exc)
        out["other_collections"] = others

        if count == 0:
            out["status"] = "empty"
            rich = {k: v for k, v in others.items() if v > 0}
            if rich:
                biggest = max(rich, key=rich.get)
                out["warning"] = (
                    f"当前 collection「{self.collection_name}」为空，但同库存在非空 collection"
                    f"「{biggest}」（{rich[biggest]} 块）——通常是更换嵌入模型导致 collection 名变化，"
                    f"旧语料没有被读回。请执行 python scripts/ingest_policy_docs.py 重建。"
                )
            else:
                out["warning"] = (
                    "知识库为空：政策问答将返回空结果。"
                    "请执行 python scripts/ingest_policy_docs.py（全新 clone 必须先跑一次）。"
                )
        return out

    def source_hashes(self) -> Dict[str, str]:
        """已入库文档 → 内容哈希（旧版入库无哈希时为空串，会触发重新入库）。"""
        if self.count() == 0:
            return {}
        out: Dict[str, str] = {}
        for _, meta in self._corpus()["by_id"].values():
            out.setdefault(meta.get("source", ""), meta.get("doc_hash", ""))
        return out

    def prune_stale_collections(self, dry_run: bool = True) -> Dict:
        """清理同一 persist_dir 下不再被当前配置读取的历史 collection。

        换嵌入模型会让 collection 名跟着变（见 ``health`` 的说明），旧 collection
        本体、它的向量索引目录、以及它对应的 ``*_fallback_docs.json`` 都会留在
        磁盘上。它们不影响检索正确性，但会持续占盘、并且让 ``health`` 的
        other_collections 越来越长——排查「库为什么空了」时反而更难看清。

        Args:
            dry_run: 默认 True，只返回计划不删除。删除不可逆，必须显式传 False。

        Returns:
            dict，含 kept（当前 collection 名）、removed（已删/待删的
            collection 名 → 块数）、freed_bytes、dry_run。
        """
        out: Dict = {
            "kept": self.collection_name,
            "removed": {},
            "freed_bytes": 0,
            "dry_run": dry_run,
        }
        if not self._chroma_ok:
            out["error"] = f"ChromaDB 不可用（{self._degrade_reason}）"
            return out

        stale: Dict[str, int] = {}
        try:
            for col in self.client.list_collections():
                name = col if isinstance(col, str) else getattr(col, "name", str(col))
                if name == self.collection_name:
                    continue
                try:
                    stale[name] = self.client.get_collection(name).count()
                except Exception:  # pragma: no cover
                    stale[name] = -1
        except Exception as exc:  # pragma: no cover
            out["error"] = f"列举 collection 失败：{exc}"
            return out

        out["removed"] = stale
        if dry_run or not stale:
            return out

        persist = Path(self.persist_dir)
        for name in stale:
            try:
                self.client.delete_collection(name)
            except Exception as exc:  # pragma: no cover
                logger.warning("删除 collection %s 失败：%s", name, exc)
                continue
            # 该 collection 的 BM25 回退缓存同样失效
            cache = persist / f"{name}_fallback_docs.json"
            if cache.exists():
                try:
                    out["freed_bytes"] += cache.stat().st_size
                    cache.unlink()
                except OSError:  # pragma: no cover
                    pass
        self._invalidate_caches()
        return out

    def remove_source(self, doc_source: str):
        if self._chroma_ok:
            self.collection.delete(where={"source": doc_source})
        else:
            import json
            self._fallback_docs = [d for d in self._fallback_docs
                                   if d.get("metadata", {}).get("source") != doc_source]
            self.fallback_cache_file.write_text(
                json.dumps(self._fallback_docs, ensure_ascii=False, indent=2), encoding="utf-8")
        self._invalidate_caches()

    def clear(self):
        if self._chroma_ok:
            try:
                self.client.delete_collection(self.collection_name)
            except Exception:
                pass
            self._init_chroma()
        else:
            self._fallback_docs = []
            if self.fallback_cache_file.exists():
                self.fallback_cache_file.unlink()
        self._invalidate_caches()


@lru_cache(maxsize=2)
def get_vector_store(persist_dir: str | None = None) -> PolicyVectorStore:
    """进程级单例：避免每个 API 请求都重新加载嵌入模型与 BM25 索引。"""
    return PolicyVectorStore(persist_dir=persist_dir)
