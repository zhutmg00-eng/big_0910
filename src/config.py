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

LLM_MODEL = os.getenv("LLM_MODEL", "deepseek-chat")

# Embedding配置
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "chromadb-default")

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
RETRIEVAL_THRESHOLD = 0.7  # 相似度阈值
LLM_TEMPERATURE = 0.1  # 低温度减少幻觉
LLM_MAX_TOKENS = 2000  # 最大输出长度
