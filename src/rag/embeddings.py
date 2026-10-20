"""嵌入模型适配层。

v0.4 起向量库不再把嵌入函数“托管”给 ChromaDB，而是由本模块显式计算
文档向量与查询向量后再写入 / 查询。这样做有三个好处：

1. 可以为 BGE 等非对称检索模型给查询加检索指令前缀（文档侧不加）；
2. 不依赖 ChromaDB 1.x 的嵌入函数持久化配置，换模型不会触发兼容告警；
3. 便于在评测脚本中对“嵌入模型”做消融实验。

支持的 EMBEDDING_MODEL 取值：

- ``fastembed:<model>``：基于 ONNX Runtime 的本地模型（无需 PyTorch），
  推荐 ``fastembed:BAAI/bge-small-zh-v1.5``（中文，512 维，约 90MB）。
- ``chromadb-default`` / ``default``：ChromaDB 自带 all-MiniLM-L6-v2（英文模型，
  对中文语义区分度很弱，仅作为兼容与对照基线保留）。
- ``openai:<model>``：OpenAI 兼容嵌入接口，需要 ``OPENAI_API_KEY``。
- ``bge-local`` / ``sentence-transformers:<model>``：需要额外安装 PyTorch。

国内网络环境下可设置 ``HF_ENDPOINT=https://hf-mirror.com`` 加速模型下载。
"""
from __future__ import annotations

import os
from functools import lru_cache
from typing import List, Sequence

from src.config import MODEL_CACHE_DIR, OPENAI_API_KEY

# BGE 中文模型官方推荐的“短查询→长段落”检索指令
BGE_ZH_QUERY_INSTRUCTION = "为这个句子生成表示以用于检索相关文章："

RECOMMENDED_EMBEDDING = "fastembed:BAAI/bge-small-zh-v1.5"
LEGACY_EMBEDDING = "chromadb-default"


def fastembed_available() -> bool:
    try:
        import fastembed  # noqa: F401
        return True
    except ImportError:
        return False


def resolve_embedding_setting(setting: str | None) -> str:
    """把用户配置解析为实际可用的嵌入设置（缺依赖时降级并给出提示）。"""
    value = (setting or "").strip() or "auto"
    if value.lower() == "auto":
        return RECOMMENDED_EMBEDDING if fastembed_available() else LEGACY_EMBEDDING
    if value.lower().startswith("fastembed") and not fastembed_available():
        print("[WARN] 未安装 fastembed，嵌入模型降级为 chromadb-default（中文检索效果会明显下降）")
        return LEGACY_EMBEDDING
    return value


class BaseEmbedder:
    name: str = "base"

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        raise NotImplementedError

    def embed_query(self, text: str) -> List[float]:
        return self.embed_documents([text])[0]


class FastEmbedEmbedder(BaseEmbedder):
    """ONNX 本地嵌入（推荐）。"""

    def __init__(self, model_name: str):
        from fastembed import TextEmbedding

        self.name = f"fastembed:{model_name}"
        self.model_name = model_name
        cache_dir = os.getenv("FASTEMBED_CACHE_PATH") or str(MODEL_CACHE_DIR)
        self._model = TextEmbedding(model_name=model_name, cache_dir=cache_dir)
        lower = model_name.lower()
        self.query_prefix = BGE_ZH_QUERY_INSTRUCTION if "bge" in lower and "zh" in lower else ""

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return [vec.tolist() for vec in self._model.embed(list(texts), batch_size=32)]

    def embed_query(self, text: str) -> List[float]:
        return next(iter(self._model.embed([self.query_prefix + text]))).tolist()


class ChromaFunctionEmbedder(BaseEmbedder):
    """包装 ChromaDB 内置嵌入函数（默认 / OpenAI / SentenceTransformer）。"""

    def __init__(self, setting: str):
        from chromadb.utils import embedding_functions

        self.name = setting
        lower = setting.lower()
        if lower in {"default", "chromadb-default"}:
            self._fn = embedding_functions.DefaultEmbeddingFunction()
        elif lower == "openai" or lower.startswith("openai:"):
            if not OPENAI_API_KEY:
                raise RuntimeError("EMBEDDING_MODEL 使用 OpenAI 时必须设置 OPENAI_API_KEY")
            model_name = setting.split(":", 1)[1] if ":" in setting else "text-embedding-3-small"
            self._fn = embedding_functions.OpenAIEmbeddingFunction(
                api_key=OPENAI_API_KEY, model_name=model_name
            )
        elif lower == "bge-local" or lower.startswith("sentence-transformers:"):
            model_name = setting.split(":", 1)[1] if ":" in setting else "BAAI/bge-small-zh-v1.5"
            self._fn = embedding_functions.SentenceTransformerEmbeddingFunction(
                model_name=model_name, normalize_embeddings=True
            )
        else:
            raise ValueError(
                "不支持的 EMBEDDING_MODEL；可用 auto、fastembed:<model>、chromadb-default、"
                "openai:<model> 或 sentence-transformers:<model>"
            )

    def embed_documents(self, texts: Sequence[str]) -> List[List[float]]:
        return [list(map(float, v)) for v in self._fn(list(texts))]


@lru_cache(maxsize=4)
def get_embedder(setting: str) -> BaseEmbedder:
    """按设置创建（并进程内缓存）嵌入器；模型只加载一次。"""
    if setting.lower().startswith("fastembed"):
        model_name = setting.split(":", 1)[1] if ":" in setting else "BAAI/bge-small-zh-v1.5"
        return FastEmbedEmbedder(model_name)
    return ChromaFunctionEmbedder(setting)
