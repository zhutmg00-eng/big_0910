"""政策问答数据模型"""
from pydantic import BaseModel, Field, field_validator
from typing import Optional


class PolicyQuestion(BaseModel):
    """政策问答输入"""
    question: str = Field(
        ...,
        min_length=1,
        max_length=500,
        description="用户自然语言问题",
    )
    carbon_profile: dict = Field(default_factory=dict, description="企业碳画像数据")

    @field_validator("question")
    @classmethod
    def normalize_question(cls, value: str) -> str:
        question = value.strip()
        if not question:
            raise ValueError("问题不能为空")
        return question


class RetrievedSource(BaseModel):
    """检索到的政策来源"""
    source: str = Field(..., description="来源文件名")
    date: str = Field("", description="发布日期")
    relevance: Optional[float] = Field(None, description="相关度")
    chunk_id: str = Field("", description="知识库分块 ID（可溯源到原文）")
    excerpt: str = Field("", description="命中段落摘录")
    retrievers: list[str] = Field(default_factory=list, description="命中该段落的检索器")


class PolicyAnswer(BaseModel):
    """政策问答输出"""
    question: str = Field(..., description="原始提问")
    retrieved_sources: list[RetrievedSource] = Field(default_factory=list, description="检索到的政策依据片段")
    answer: str = Field(..., description="合规问答结论或溯源建议")
    evidence_count: int = Field(
        0,
        description=(
            "实际检索到的证据条数（= len(retrieved_sources)，显式给出便于调用方"
            "在证据为空时告警；证据为 0 时 answer 不含任何政策条款引用）"
        ),
    )
    evidence_warning: str = Field(
        "",
        description="证据为空时的说明。非空表示回答未基于任何检索证据，不应作为政策依据引用。",
    )
    latency_ms: Optional[float] = Field(None, description="检索+生成耗时（毫秒）")
