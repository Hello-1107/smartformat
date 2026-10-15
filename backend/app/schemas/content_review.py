"""AI 内容审查契约，与格式合规结果独立。"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class ContentParagraph(BaseModel):
    index: int
    text: str


class ContentIssue(BaseModel):
    paragraph_index: int = Field(ge=0, strict=True)
    quote: str = Field(min_length=1, max_length=2000)
    category: Literal["措辞", "语法", "逻辑", "一致性", "事实待核实", "其他"]
    severity: Literal["重要", "一般", "建议"]
    reason: str = Field(min_length=1, max_length=2000)
    suggestion: str = Field(min_length=1, max_length=3000)


class ContentReviewResult(BaseModel):
    summary: str = Field(min_length=1, max_length=3000)
    issues: list[ContentIssue] = Field(max_length=50)


class ContentReviewCreate(BaseModel):
    workspace_id: int
    document_id: int
    instructions: str = Field(default="", max_length=1000)


class ContentReviewOut(ContentReviewResult):
    id: int
    workspace_id: int
    document_id: int
    instructions: str
    model: str
    paragraph_count: int
    created_at: datetime
