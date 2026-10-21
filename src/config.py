"""全局配置 — API密钥、路径、参数"""
import os
from pathlib import Path
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# ============================================================
# 路径配置
# ============================================================
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
POLICY_DOCS_DIR = DATA_DIR / "policy_docs"
CHROMA_DB_DIR = DATA_DIR / "chroma_db"
MODEL_CACHE_DIR = Path(os.getenv("MODEL_CACHE_DIR", str(DATA_DIR / "models")))

# 确保目录存在
for d in [DATA_DIR, RAW_DIR, PROCESSED_DIR, POLICY_DOCS_DIR, CHROMA_DB_DIR]:
    d.mkdir(parents=True, exist_ok=True)

# ============================================================
# LLM API 配置
# ============================================================
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY", "")
DASHSCOPE_API_KEY = os.getenv("DASHSCOPE_API_KEY", "")
ZHIPU_API_KEY = os.getenv("ZHIPU_API_KEY", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")

LLM_MODEL = os.getenv("LLM_MODEL") or "deepseek-chat"

# Embedding配置
# auto：已安装 fastembed 时使用中文 BGE 模型（推荐），否则降级为 chromadb-default
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "auto")

# 根据模型选择API配置
def get_llm_config(model: str = None) -> dict:
    """返回LLM API配置"""
    model = model or LLM_MODEL
    if "deepseek" in model:
        return {
            "api_key": DEEPSEEK_API_KEY,
            "base_url": "https://api.deepseek.com",
            "model": model,
        }
    elif "qwen" in model:
        return {
            "api_key": DASHSCOPE_API_KEY,
            "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            "model": model,
        }
    elif "glm" in model:
        return {
            "api_key": ZHIPU_API_KEY,
            "base_url": "https://open.bigmodel.cn/api/paas/v4",
            "model": model,
        }
    else:
        return {
            "api_key": OPENAI_API_KEY,
            "base_url": "https://api.openai.com/v1",
            "model": model,
        }

# ============================================================
# 碳排放计算参数
# ============================================================
# 满载率调整系数
LOAD_FACTOR_ALPHA = 0.15
LOAD_FACTOR_THRESHOLD = 0.75

# ============================================================
# RAG参数
# ============================================================
CHUNK_SIZE = 800       # 政策文档切分大小（字符）
CHUNK_OVERLAP = 150    # 重叠字符数
RETRIEVAL_TOP_K = 5    # 检索返回数量
# 默认检索模式：rrf3 = BM25 + 稠密向量 + 字面规则 三路倒数排名融合（Recall@10 最高，见 docs/rag_benchmark）
# 可选：rrf3 | rrf | rerank | hybrid(v0.3 加权重排) | bm25 | vector | keyword
RETRIEVAL_MODE = (os.getenv("RETRIEVAL_MODE") or "rrf3").lower()
RRF_K = 60             # RRF 常数（Cormack et al. 2009 推荐值，不针对评测集调参）
RRF_CANDIDATES = 50    # 每路检索器参与融合的候选数

# RRF 各检索路的先验权重。
# 等权融合（1:1:1）会用一个 Top-1 准确率仅 12.5% 的检索器去稀释 Top-1 准确率
# 40% 的检索器，实测使 MRR 从 0.488 降到 0.411（见 docs/rag_benchmark）。
# 权重依据各检索路的 Top-1 命中率（keyword 16/40、bm25 12/40、vector 5/40）设定，
# 并留有平台容差：w_vector 取 0.05~0.2 之间结果稳定，非在评测集上精调得到。
RRF_WEIGHTS = {
    "bm25": float(os.getenv("RRF_WEIGHT_BM25") or 0.6),
    "vector": float(os.getenv("RRF_WEIGHT_VECTOR") or 0.1),
    "keyword": float(os.getenv("RRF_WEIGHT_KEYWORD") or 0.8),
}
# 检索相关度的「低置信」提示阈值。注意它不用于过滤（过滤会改变实测指标，
# 必须重跑金标集才能对外引用），只用于在答复旁标注「这些条款可能不对题」。
# 定标依据：实测「?"这样的空问题」也能拿到相关性 0.50~0.53 的 5 条证据
# （稠密向量对任意输入都会给出 0.5 左右的余弦相似度），而真正对题的提问通常
# 在 0.62 以上，故取 0.62 作为提示线。
RETRIEVAL_THRESHOLD = float(os.getenv("RETRIEVAL_THRESHOLD") or 0.62)
LLM_TEMPERATURE = 0.1  # 低温度减少幻觉
LLM_MAX_TOKENS = 2000  # 最大输出长度
