"""ChromaDB向量知识库管理

支持两种模式：
1. ChromaDB模式（推荐）：语义向量检索，需安装chromadb
2. 关键词模式（fallback）：TF-IDF关键词检索，无需额外依赖
"""
from typing import List, Dict, Optional
from pathlib import Path
import hashlib
import re
from src.config import CHROMA_DB_DIR, EMBEDDING_MODEL, OPENAI_API_KEY

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
    """碳交易政策向量知识库

    自动选择ChromaDB（已安装）或关键词检索（未安装）模式
    """

    def __init__(self, persist_dir: str = None):
        self.persist_dir = persist_dir or str(CHROMA_DB_DIR)
        self.embedding_model = EMBEDDING_MODEL.strip() or "chromadb-default"
        model_id = hashlib.sha1(self.embedding_model.encode("utf-8")).hexdigest()[:8]
        self.collection_name = f"carbon_policy_v4_{model_id}"
        self.fallback_cache_file = (
            Path(self.persist_dir) / f"{self.collection_name}_fallback_docs.json"
        )
        self._fallback_docs: List[Dict] = []  # 关键词模式的文档存储

        if CHROMA_AVAILABLE:
            self.embedding_function = self._build_embedding_function()
            self._init_chroma()
        else:
            self._init_fallback()

    def _build_embedding_function(self):
        """根据 EMBEDDING_MODEL 创建 Chroma 实际使用的嵌入函数。"""
        from chromadb.utils import embedding_functions

        setting = self.embedding_model.lower()
        if setting in {"default", "chromadb-default"}:
            return embedding_functions.DefaultEmbeddingFunction()

        if setting == "openai" or setting.startswith("openai:"):
            if not OPENAI_API_KEY:
                raise RuntimeError("EMBEDDING_MODEL 使用 OpenAI 时必须设置 OPENAI_API_KEY")
            model_name = self.embedding_model.split(":", 1)[1] if ":" in self.embedding_model else "text-embedding-3-small"
            return embedding_functions.OpenAIEmbeddingFunction(
                api_key=OPENAI_API_KEY,
                model_name=model_name,
            )

        if setting == "bge-local" or setting.startswith("sentence-transformers:"):
            model_name = (
                self.embedding_model.split(":", 1)[1]
                if ":" in self.embedding_model
                else "BAAI/bge-small-zh-v1.5"
            )
            return embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=model_name,
                normalize_embeddings=True,
            )

        raise ValueError(
            "不支持的 EMBEDDING_MODEL；可用 chromadb-default、openai:<model> 或 sentence-transformers:<model>"
        )

    def _init_chroma(self):
        """初始化ChromaDB"""
        self.client = chromadb.PersistentClient(path=self.persist_dir)
        try:
            self.collection = self.client.get_collection(
                self.collection_name,
                embedding_function=self.embedding_function,
            )
        except Exception:
            self.collection = self.client.create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
                metadata={
                    "description": "中国碳交易与交通低碳政策知识库",
                    "embedding_model": self.embedding_model,
                },
            )
            print("[OK] 已创建新ChromaDB知识库")
        else:
            print(f"[OK] 已加载ChromaDB知识库: {self.collection.count()} 个文档块")

    def _init_fallback(self):
        """初始化关键词检索模式"""
        # 尝试从JSON加载之前入库的文档
        import json
        if self.fallback_cache_file.exists():
            self._fallback_docs = json.loads(
                self.fallback_cache_file.read_text(encoding="utf-8")
            )
            print(f"[OK] 已加载关键词检索知识库: {len(self._fallback_docs)} 个文档块")
        else:
            print("[OK] 已创建新关键词检索知识库（ChromaDB未安装）")

    def add_documents(self, chunks: List[Dict], doc_source: str, doc_date: str = ""):
        """向知识库添加文档chunk"""
        if not chunks:
            return

        if CHROMA_AVAILABLE:
            self._add_chroma(chunks, doc_source, doc_date)
        else:
            self._add_fallback(chunks, doc_source, doc_date)

    def _add_chroma(self, chunks: List[Dict], doc_source: str, doc_date: str = ""):
        """ChromaDB模式入库"""
        ids = []
        documents = []
        metadatas = []

        for i, chunk in enumerate(chunks):
            chunk_id = f"{doc_source}_{i}"
            ids.append(chunk_id)
            documents.append(f"来源文档：{doc_source}\n{chunk['text']}")
            metadatas.append({
                "source": doc_source,
                "date": doc_date,
                "chunk_index": i,
                **chunk.get("metadata", {}),
            })

        self.collection.upsert(ids=ids, documents=documents, metadatas=metadatas)
        print(f"[OK] 已入库 {len(chunks)} 个文档块 来自: {doc_source}")

    def _add_fallback(self, chunks: List[Dict], doc_source: str, doc_date: str = ""):
        """关键词模式入库"""
        import json
        self._fallback_docs = [
            doc for doc in self._fallback_docs
            if doc.get("metadata", {}).get("source") != doc_source
        ]
        for i, chunk in enumerate(chunks):
            self._fallback_docs.append({
                "id": f"{doc_source}_{i}",
                "text": chunk["text"],
                "metadata": {
                    "source": doc_source,
                    "date": doc_date,
                    "chunk_index": i,
                    **chunk.get("metadata", {}),
                },
            })

        # 持久化到JSON
        self.fallback_cache_file.parent.mkdir(parents=True, exist_ok=True)
        self.fallback_cache_file.write_text(
            json.dumps(self._fallback_docs, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"[OK] 已入库 {len(chunks)} 个文档块 来自: {doc_source}")

    def search(self, query: str, k: int = 5, mode: str = "hybrid") -> List[Dict]:
        """检索最相关的政策条款 (mode: 'hybrid' | 'vector' | 'keyword')"""
        if mode == "vector":
            return self.search_vector_only(query, k)
        elif mode == "keyword":
            return self.search_keyword_only(query, k)

        if CHROMA_AVAILABLE:
            return self._search_chroma(query, k)
        else:
            return self._search_tfidf(query, k)

    def search_vector_only(self, query: str, k: int = 5) -> List[Dict]:
        """纯语义向量检索（基于嵌入相似度，不加关键词重排）"""
        if not CHROMA_AVAILABLE:
            return self._search_tfidf(query, k)
        total = self.collection.count()
        if total == 0:
            return []
        target_k = min(total, k)
        results = self.collection.query(query_texts=[query], n_results=target_k)
        formatted = []
        if results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                chunk_id = results["ids"][0][i] if results.get("ids") else ""
                metadata = results["metadatas"][0][i] if results.get("metadatas") else {}
                distance = results["distances"][0][i] if results.get("distances") else 1.0
                formatted.append({
                    "id": chunk_id,
                    "text": results["documents"][0][i],
                    "metadata": metadata,
                    "distance": float(distance),
                })
        return formatted

    def search_keyword_only(self, query: str, k: int = 5) -> List[Dict]:
        """纯关键词/字面重叠检索（基于字面覆盖率与领域词匹配，不使用向量嵌入）"""
        if not CHROMA_AVAILABLE:
            return self._search_tfidf(query, k)
        total = self.collection.count()
        if total == 0:
            return []
        # 获取全量文档进行轻量字面评分
        all_items = self.collection.get(include=["documents", "metadatas"])
        scored = []
        docs = all_items.get("documents", [])
        ids = all_items.get("ids", [])
        metas = all_items.get("metadatas", [])
        for i, text in enumerate(docs):
            meta = metas[i] if i < len(metas) else {}
            cid = ids[i] if i < len(ids) else ""
            source = meta.get("source", "")
            lex_score = _lexical_relevance(query, text, source)
            scored.append({
                "id": cid,
                "text": text,
                "metadata": meta,
                "distance": 1.0 - lex_score,
                "lexical_score": lex_score,
            })
        scored.sort(key=lambda item: item["distance"])
        return scored[:k]

    def _search_chroma(self, query: str, k: int = 5) -> List[Dict]:
        """ChromaDB 语义召回后，用标题和中文关键词覆盖率混合重排。"""
        total = self.collection.count()
        if total == 0:
            return []
        candidate_count = min(total, max(k * 50, 500))
        results = self.collection.query(query_texts=[query], n_results=candidate_count)

        formatted = []
        if results["documents"] and results["documents"][0]:
            for i in range(len(results["documents"][0])):
                chunk_id = results["ids"][0][i] if results.get("ids") else ""
                metadata = results["metadatas"][0][i] if results["metadatas"] else {}
                distance = results["distances"][0][i] if results["distances"] else 1.0
                semantic_score = 1.0 / (1.0 + max(float(distance), 0.0))
                lexical_score = _lexical_relevance(
                    query,
                    results["documents"][0][i],
                    metadata.get("source", ""),
                )
                combined_score = 0.35 * semantic_score + 0.65 * lexical_score
                formatted.append({
                    "id": chunk_id,
                    "text": results["documents"][0][i],
                    "metadata": metadata,
                    "distance": 1.0 - combined_score,
                })
        formatted.sort(key=lambda item: item["distance"])
        return formatted[:k]
    def _search_tfidf(self, query: str, k: int = 5) -> List[Dict]:
        """TF-IDF关键词检索（fallback模式）

        简单但有效的中文文本检索：
        1. 对query进行字符级n-gram分词（2-4 gram）
        2. 计算TF-IDF相似度
        3. 返回Top-K结果
        """
        if not self._fallback_docs:
            return []

        # 生成n-gram
        def get_ngrams(text: str, n: int = 2) -> List[str]:
            text = re.sub(r"\s+", "", text)
            return [text[i:i+n] for i in range(len(text) - n + 1)] if len(text) >= n else [text]

        query_ngrams = set(get_ngrams(query, 2) + get_ngrams(query, 3))

        # 计算每个文档的得分
        scored = []
        for doc in self._fallback_docs:
            doc_ngrams = set(get_ngrams(doc["text"], 2) + get_ngrams(doc["text"], 3))

            # Jaccard相似度
            if query_ngrams and doc_ngrams:
                intersection = len(query_ngrams & doc_ngrams)
                union = len(query_ngrams | doc_ngrams)
                score = intersection / union if union > 0 else 0
            else:
                score = 0

            # 额外关键词加权
            keywords = ["碳排放", "配额", "碳交易", "物流", "运输", "排放因子",
                       "碳市场", "清缴", "核查", "报告", "罚款", "履约"]
            for kw in keywords:
                if kw in query and kw in doc["text"]:
                    score += 0.1

            lexical_score = _lexical_relevance(
                query,
                doc["text"],
                doc.get("metadata", {}).get("source", ""),
            )
            combined_score = 0.35 * min(score, 1.0) + 0.65 * lexical_score
            scored.append((combined_score, doc))

        # 排序取Top-K
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, doc in scored[:k]:
            results.append({
                "text": doc["text"],
                "metadata": doc.get("metadata", {}),
                "distance": 1 - score,  # 模拟distance（越小越相关）
            })
        return results

    def get_stats(self) -> dict:
        """获取知识库统计信息"""
        if CHROMA_AVAILABLE:
            return {
                "total_chunks": self.collection.count(),
                "collection_name": self.collection_name,
                "mode": "chromadb",
                "embedding_model": self.embedding_model,
            }
        else:
            return {
                "total_chunks": len(self._fallback_docs),
                "collection_name": self.collection_name,
                "mode": "tfidf_fallback",
                "embedding_model": "keyword-ngram",
            }

    def clear(self):
        """清空知识库"""
        if CHROMA_AVAILABLE:
            self.client.delete_collection(self.collection_name)
            self.collection = self.client.create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_function,
                metadata={
                    "description": "中国碳交易与交通低碳政策知识库",
                    "embedding_model": self.embedding_model,
                },
            )
        else:
            self._fallback_docs = []
            if self.fallback_cache_file.exists():
                self.fallback_cache_file.unlink()
        print("[OK] 知识库已清空")
