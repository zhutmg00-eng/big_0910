"""RAG政策解析助手 - 完整调用链路"""
import hashlib
import logging
from pathlib import Path

from src.rag.vector_store import PolicyVectorStore, get_vector_store
from src.rag.generator import SYSTEM_PROMPT, build_retrieval_answer, build_user_prompt, call_llm
from src.config import RETRIEVAL_THRESHOLD, RETRIEVAL_TOP_K
from src.rag.parser import _CJK_GAP

logger = logging.getLogger(__name__)


class PolicyAdvisor:
    """碳交易政策顾问"""

    def __init__(self, vector_store: PolicyVectorStore = None):
        self.vs = vector_store or get_vector_store()

    def ask(
        self,
        question: str,
        carbon_profile: dict,
        top_k: int = None,
    ) -> dict:
        """
        单次问答

        Args:
            question: 用户自然语言问题
            carbon_profile: 企业碳画像数据
            top_k: 检索返回数量

        Returns:
            dict: {question, retrieved_sources, answer, evidence_count, evidence_warning}

        ``evidence_count == 0`` 表示未检索到任何证据，此时不调用大模型，
        直接返回说明性提示（见下方无证据短路），避免编造政策依据。
        """
        top_k = top_k or RETRIEVAL_TOP_K

        # 1. 检索（第二道兜底：检索层任何异常都不让 /api/ask 返回 500）
        try:
            retrieved = self.vs.search(question, k=top_k)
            retrieval_mode = self.vs.search_mode() if hasattr(self.vs, "search_mode") else ""
        except Exception as exc:  # pragma: no cover - 防御性
            logger.exception("知识库检索失败，返回空证据：%s", exc)
            retrieved = []
            retrieval_mode = ""

        # 2. 无证据短路：绝不把"空知识库"交给 LLM 自由生成
        #
        # 实测（2026-10）：知识库为空时，原实现会把空证据塞进 prompt 照常调 LLM，
        # 模型先如实说"未检索到任何相关政策条款"，紧接着又输出
        # "全国碳市场目前仅覆盖发电、钢铁、水泥、电解铝等重点排放行业，
        #  物流运输行业未被纳入配额管理范围"——这句话没有任何检索证据支撑，
        # 而检索层与日志都不报错。对一个以"可溯源"为卖点的政策问答，
        # 这比直接报错危险得多。因此证据为空时直接返回显式提示，不调 LLM。
        if not retrieved:
            return {
                "question": question,
                "retrieved_sources": [],
                # 面向终端用户（车队老板）的话术：先说结论与原因，再说怎么办。
                # 第 8 轮评审 P1-1：原实现把 `GET /api/kb/health`、
                # `python scripts/ingest_policy_docs.py --force` 这些开发者命令
                # 直接当成给用户的答复，老板看不懂；运维信息应是附带而非主体。
                "answer": (
                    "这个问题在现有政策语料里没有找到可引用的条款，所以本次不作答。\n\n"
                    "我们宁可说「没找到」，也不凭印象给出一条查不到出处的结论——"
                    "政策问答一旦编造依据，比不给答案危险得多。\n\n"
                    "你可以：\n"
                    "1. 换个说法再问一次（例如把「我的车要不要交碳税」改成"
                    "「物流企业是否纳入全国碳排放权交易市场」）；\n"
                    "2. 问与运输低碳、排放核算、碳市场相关的主题；\n"
                    "3. 若这是刚部署的新环境，知识库可能还没导入政策文件，"
                    "请联系系统管理员把政策语料导入后再试。"
                ),
                "evidence_count": 0,
                "evidence_warning": (
                    "本次没有找到可引用的政策条款，因此未生成回答，也不含任何条款引用。"
                    "（运维提示：GET /api/kb/health 查看知识库状态，"
                    "status=empty 时执行 python scripts/ingest_policy_docs.py --force 入库。）"
                ),
            }

        # 3. 构建Prompt
        user_prompt = build_user_prompt(question, retrieved, carbon_profile)

        # 4. 调用LLM
        fallback_answer = build_retrieval_answer(question, retrieved)
        answer = call_llm(SYSTEM_PROMPT, user_prompt, fallback_answer=fallback_answer)

        sources = []
        for index, r in enumerate(retrieved, start=1):
            # 检索层没填 rank（bm25 / hybrid / rerank 分支）时按顺序补齐，
            # 支持度判定要用它，缺了就一律会被判成「没进前三名」。
            if not r.get("rank"):
                r = {**r, "rank": index}
            relevance, basis = _result_relevance(r)
            sources.append({
                "source": r["metadata"].get("source", "未知"),
                "date": r["metadata"].get("date", ""),
                # 只有 vector（cosine）与 keyword（字面覆盖率）是真相关度；
                # 融合模式下的 1-distance 是「各路名次一致性」，rrf3 三路都排第一
                # 反而等于 0，当相关度会必然触发伪告警，所以单独放进 rank_agreement。
                "relevance": relevance,
                "relevance_basis": basis,
                "relevance_mode": retrieval_mode,
                "rank_agreement": r.get("agreement"),
                "chunk_id": r.get("id", ""),
                "excerpt": _excerpt(r.get("text", "")),
                "retrievers": r.get("retrievers", []),
            })

        return {
            "question": question,
            "retrieved_sources": sources,
            "answer": answer,
            "evidence_count": len(retrieved),
            "evidence_warning": _low_relevance_warning(sources),
        }

    def ingest_document(self, file_path, doc_date: str = ""):
        """导入一份政策文档到知识库"""
        from src.rag.parser import process_document
        from pathlib import Path

        file_path = Path(file_path)
        chunks = process_document(file_path, doc_date)
        self.vs.add_documents(chunks, file_path.name, doc_date)
        return len(chunks)


#: 这些检索模式下 ``1 - distance`` 才有「相关度」含义。
#: vector 是 cosine 相似度；keyword 是字面覆盖率（乘了 weight 系数，>1 时钳到 1）。
_CORRELATION_MODES = {"vector", "keyword"}

#: keyword 模式里字面覆盖率直接当相关度的下限：中文政策问句里能对上词，
#: 基本都算「有据可查」。
_LEXICAL_MIN_COVERAGE = 0.35

#: 融合检索的判定线：第一名同时被 ≥2 个检索器召回、且名次在各项前三名之内。
#: 实测（39 份 / 281 块）：对题问题全部满足；噪音问题（今天天气怎么样）
#: 与蹭关键词问题（航空煤油碳排放因子）全部不满足。
_RELEVANT_MIN_SUPPORT = 2
_RELEVANT_MAX_RANK = 3


def _result_relevance(result: dict):
    """返回 ``(relevance, 判定依据)``；没有可解释相关度时 relevance 为 None。

    第 10 轮评审实测了一个会被评委当场问住的口径错误：融合检索里
    ``1 - distance`` 是 RRF 名次分位——被三路同时排第一的 chunk 得分接近
    ``max_possible``，于是 ``relevance ≈ 0.00``，**完全对题**的「配额清缴期限」
    反而触发「最高相关性只有 0.00，可能并不对题」；而「我想请假」在 rrf3 下
    ``relevance = 0.994``，比真正对题的问题还高。

    按检索模式分开处理：
    - vector / keyword：直接用 1-distance（cosine / 字面覆盖率），是真相关度；
    - bm25 / rrf / rrf3 / hybrid / rerank：**不给相关度**，改判「有没有据可查」，
      依据是跨检索器召回支持度与名次，返回 0.0/1.0 两个离散值。这个判定只用于
      决定「要不要提示用户可能不对题」，不参与任何指标计算与排序。
    """
    if result.get("distance") is None:
        return None, "unknown"
    retrievers = result.get("retrievers") or []
    if not retrievers:
        return None, "unknown"
    if all(name in _CORRELATION_MODES for name in retrievers):
        score = 1 - result["distance"]
        if "keyword" in retrievers and result.get("score") is not None:
            score = min(1.0, max(0.0, float(result["score"])))
        return round(score, 3), "correlation"
    support = len(retrievers)
    rank = result.get("rank") or 0
    if support >= _RELEVANT_MIN_SUPPORT and 0 < rank <= _RELEVANT_MAX_RANK:
        return 1.0, "multi_retriever_agreement"
    # 只被一个检索器召回：只能说明「词面挂上了」，没有交叉印证。
    return 0.0, "single_retriever_hit"


def _low_relevance_warning(sources: list[dict]) -> str:
    """证据整体对不上时给出提示。

    第 9/10 轮评审实测：``POST /api/ask {"question":"?"}`` 返回 200、
    evidence_count=5、evidence_warning=""，而 5 条证据的相关性只有
    0.501–0.533。检索层永远不会返回空（稠密向量对任何输入都给 0.5 左右），
    所以「检索到了」并不等于「对题」——不提示的话，用户会看到一段以错位
    条款为依据、语气却很确定的答复。

    只做提示、不做过滤：过滤会改变已对外引用的检索指标（MRR/Recall），
    要改必须重跑 40 题金标集，属于另一件事。
    """
    scored = [s for s in sources if s.get("relevance") is not None]
    if not scored:
        return ""
    basis = {s.get("relevance_basis") for s in scored}
    rrf_supported = [s for s in sources if s.get("relevance_basis") == "multi_retriever_agreement"]
    if rrf_supported and len(rrf_supported) < min(_RELEVANT_MIN_SUPPORT + 1, len(sources)):
        # 融合检索里只有 1 条拿到交叉印证：说明各路排序分歧很大。
        # 这比「完全没印证」轻，但也不该像完全对题那样静默放行。
        return (
            f"检索到 {len(sources)} 条条款，其中只有 {len(rrf_supported)} 条被两个以上检索器共同召回，"
            "其余几条的检索结果彼此不一致。答复可能只对上了其中一部分，"
            "建议以引用的原文条款为准。"
        )

    if basis == {"correlation"}:
        best = max(s["relevance"] for s in scored)
        if best >= _correlation_line(scored[0].get("relevance_mode")):
            return ""
        return (
            f"检索到 {len(scored)} 条条款，但最高相关性只有 {best:.2f}"
            f"（低于提示线 {_correlation_line(scored[0].get('relevance_mode')):.2f}），"
            "可能并不对题。请结合原文核对，或换一种问法。"
        )

    if any(s["relevance"] > 0 for s in scored):
        return ""
    return (
        f"检索到 {len(scored)} 条条款，但没有一条被两个以上检索器共同召回，"
        "也没有一条排进前三名，多半只是字面蹭上了关键词。"
        "请结合原文核对，或换一种问法。"
    )


#: 相关度提示线按检索模式分别设：cosine 与字面覆盖率不是同一个尺子。
#: 实测（39 份 / 281 块，5 个问题）——
#:   vector ：对题「物流企业是否纳入全国碳市场」0.634、噪音「今天天气怎么样」0.49，可区分；
#:   keyword：完全对题的「配额清缴期限」只有 0.617，用 0.62 会把正确答案判成不对题。
_CORRELATION_WARN_LINE = {"vector": 0.62, "keyword": _LEXICAL_MIN_COVERAGE}


def _correlation_line(mode) -> float:
    """返回该检索模式实际使用的提示线。

    模式专属线只是**下限**：``RETRIEVAL_THRESHOLD`` 环境变量调高时必须生效，
    调低时也不该让 vector/keyword 比配置更宽容（各自还有实测安全线）。
    """
    line = _CORRELATION_WARN_LINE.get(mode, RETRIEVAL_THRESHOLD)
    return max(line, RETRIEVAL_THRESHOLD)


def _excerpt(text: str, limit: int = 220) -> str:
    body = text.split("\n", 1)[1] if text.startswith("来源文档：") and "\n" in text else text
    body = " ".join(body.split())
    body = _CJK_GAP.sub("", body)  # 中文之间不保留排版空格
    return body[:limit] + ("…" if len(body) > limit else "")


def _guess_doc_date(name: str) -> str:
    for year in ("2027", "2026", "2025", "2024", "2023", "2022", "2021", "2020"):
        if year in name:
            return year
    return ""


def ingest_directory(directory: Path, vector_store: PolicyVectorStore | None = None,
                     force: bool = False) -> dict:
    """批量导入目录下的政策文档（md/txt/pdf/docx/html）。幂等：同名文档整体替换。"""
    from src.rag.parser import process_document

    vs = vector_store or get_vector_store()
    files = sorted(
        f for f in Path(directory).iterdir()
        if f.suffix.lower() in {".md", ".txt", ".pdf", ".docx", ".html", ".htm"}
    )
    if force:
        vs.clear()
    known = {} if force else vs.source_hashes()
    total, docs, skipped = 0, 0, 0
    for f in files:
        digest = hashlib.sha1(f.read_bytes()).hexdigest()[:16]
        if known.get(f.name) == digest:  # 内容未变：跳过，避免每次启动都重算嵌入
            skipped += 1
            continue
        date = _guess_doc_date(f.name)
        chunks = process_document(f, date)
        if not chunks:
            continue
        for c in chunks:
            c.setdefault("metadata", {})["doc_hash"] = digest
        vs.add_documents(chunks, f.name, date)
        total += len(chunks)
        docs += 1
    # 目录中已删除的文档同步移出知识库
    removed = [src for src in known if src not in {f.name for f in files}]
    for src in removed:
        vs.remove_source(src)
    return {"documents": docs, "chunks": total, "skipped": skipped, "removed": len(removed),
            "kb_documents": len(vs.source_hashes()), "kb_chunks": vs.count()}


__all__ = [
    "ingest_directory",
    "get_vector_store",
    "PolicyAdvisor",
    "PolicyVectorStore",
    "SYSTEM_PROMPT",
    "build_user_prompt",
    "build_retrieval_answer",
    "call_llm",
]
