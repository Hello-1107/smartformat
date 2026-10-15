"""审查结果 schema。"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class Violation(BaseModel):
    scope: str  # body / h1..h6 / page / heading_structure
    category: str  # font / paragraph / page / heading_structure
    field: str  # 具体字段，如 size / alignment / margin_left_cm
    expected: Any
    actual: Any
    message: str
    paragraph_index: int | None = None
    paragraph_text: str | None = None
    severity: str = "error"


class CheckSummary(BaseModel):
    total: int
    by_category: dict[str, int]
    compliant: bool


class CheckCreate(BaseModel):
    workspace_id: int
    document_id: int
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

    model_config = {"from_attributes": True}
