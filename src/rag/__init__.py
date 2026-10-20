"""RAG政策解析助手 - 完整调用链路"""
import hashlib
import logging
from pathlib import Path

from src.rag.vector_store import PolicyVectorStore, get_vector_store
from src.rag.generator import SYSTEM_PROMPT, build_retrieval_answer, build_user_prompt, call_llm
from src.config import RETRIEVAL_TOP_K
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
        except Exception as exc:  # pragma: no cover - 防御性
            logger.exception("知识库检索失败，返回空证据：%s", exc)
            retrieved = []

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
                "answer": (
                    "未在知识库中检索到与该问题相关的政策条款，因此本次不生成回答——"
                    "没有证据的作答等同于编造政策依据。\n\n"
                    "可能原因：① 知识库为空（全新 clone 后尚未入库）；"
                    "② 问题与现有政策语料主题偏离较大。\n\n"
                    "处理方式：\n"
                    "1. 检查知识库状态：`GET /api/kb/health`（status=empty 即需入库）\n"
                    "2. 入库语料：`python scripts/ingest_policy_docs.py --force`\n"
                    "3. 或换个与交通低碳、排放核算、碳市场相关的问题再试"
                ),
                "evidence_count": 0,
                "evidence_warning": (
                    "检索证据为 0 条，本次回答未调用大模型、不含任何政策条款引用。"
                    "若知识库应为空库，请先执行 scripts/ingest_policy_docs.py 入库。"
                ),
            }

        # 3. 构建Prompt
        user_prompt = build_user_prompt(question, retrieved, carbon_profile)

        # 4. 调用LLM
        fallback_answer = build_retrieval_answer(question, retrieved)
        answer = call_llm(SYSTEM_PROMPT, user_prompt, fallback_answer=fallback_answer)

        return {
            "question": question,
            "retrieved_sources": [
                {
                    "source": r["metadata"].get("source", "未知"),
                    "date": r["metadata"].get("date", ""),
                    "relevance": (
                        round(1 - r["distance"], 3)
                        if r.get("distance") is not None else None
                    ),
                    "chunk_id": r.get("id", ""),
                    "excerpt": _excerpt(r.get("text", "")),
                    "retrievers": r.get("retrievers", []),
                }
                for r in retrieved
            ],
            "answer": answer,
            "evidence_count": len(retrieved),
            "evidence_warning": "",
        }

    def ingest_document(self, file_path, doc_date: str = ""):
        """导入一份政策文档到知识库"""
        from src.rag.parser import process_document
        from pathlib import Path

        file_path = Path(file_path)
        chunks = process_document(file_path, doc_date)
        self.vs.add_documents(chunks, file_path.name, doc_date)
        return len(chunks)


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
