"""审查结果 schema。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class Violation(BaseModel):
    scope: str  # body / h1..h6 / page / heading_structure
    category: str  # font / paragraph / page / heading_structure
    field: str  # 具体字段，如 size / alignment / margin_left_cm
    expected: Any
    actual: Any
    message: str
    paragraph_index: int | None = None
    section_index: int | None = None
    run_index: int | None = None
    paragraph_text: str | None = None
    severity: str = "error"


class CheckSummary(BaseModel):
    total: int
    by_category: dict[str, int]
    compliant: bool
    status: str = "unknown"
    unknown: int = 0


class CheckCreate(BaseModel):
    workspace_id: int
    document_id: int
    rule_id: int


class BatchCheckCreate(BaseModel):
    """使用同一套规则审查多份文档。"""

    workspace_id: int
    document_ids: list[int] = Field(min_length=1, max_length=50)
    rule_id: int


class CheckOut(BaseModel):
    id: int
    workspace_id: int
    document_id: int
    rule_id: int
    status: str
    violations: list[Violation]
    summary: CheckSummary
    created_at: datetime
    ruleset_snapshot: dict | None = None

    model_config = {"from_attributes": True}


class BatchCheckOut(BaseModel):
    """批量审查的明细及适合工作区看板展示的汇总。"""

    checks: list[CheckOut]
    total_documents: int
    compliant_documents: int
    violation_total: int
