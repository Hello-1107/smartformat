"""按需生成的版本、结构及跨文档审查结果。"""

from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator


class SourceRef(BaseModel):
    document_id: int
    paragraph_index: int | None = None
    page_number: int | None = None
    quote: str | None = None


class Finding(BaseModel):
    category: str
    status: str
    message: str
    sources: list[SourceRef] = Field(default_factory=list)


class VersionCompareRequest(BaseModel):
    workspace_id: int
    original_id: int
    revised_id: int
    rule_id: int

    @model_validator(mode="after")
    def distinct_documents(self) -> "VersionCompareRequest":
        if self.original_id == self.revised_id:
            raise ValueError("请选择两份不同的文档")
        return self


class VersionCompareResult(BaseModel):
    original_id: int
    revised_id: int
    rule_id: int
    original_issue_count: int
    revised_issue_count: int
    findings: list[Finding]
    export_signature: str | None = None


class StructureCheckRequest(BaseModel):
    workspace_id: int
    document_id: int
    required_headings: list[str] = Field(default_factory=list, max_length=30)
    require_order: bool = True


class StructureCheckResult(BaseModel):
    document_id: int
    headings_found: list[str]
    findings: list[Finding]
    export_signature: str | None = None


class FieldSpec(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    aliases: list[str] = Field(default_factory=list, max_length=5)
    value_type: Literal["text", "number", "date"] = "text"

    @field_validator("name")
    @classmethod
    def clean_name(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("字段名不能为空")
        return value.strip()

    @field_validator("aliases")
    @classmethod
    def clean_aliases(cls, values: list[str]) -> list[str]:
        if any(not value.strip() or len(value) > 40 for value in values):
            raise ValueError("字段别名不能为空且不能超过 40 字符")
        return [value.strip() for value in values]


class CrossDocumentRequest(BaseModel):
    workspace_id: int
    document_ids: list[int] = Field(min_length=2, max_length=10)
    baseline_id: int
    fields: list[FieldSpec] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def valid_selection(self) -> "CrossDocumentRequest":
        if len(set(self.document_ids)) != len(self.document_ids):
            raise ValueError("文档不能重复")
        if self.baseline_id not in self.document_ids:
            raise ValueError("基准文档必须包含在核对材料中")
        if len({field.name.casefold() for field in self.fields}) != len(self.fields):
            raise ValueError("核对字段名称不能重复")
        return self


class FieldValue(BaseModel):
    document_id: int
    value: str | None = None
    normalized_value: str | None = None
    source: SourceRef | None = None
    status: Literal["match", "different", "missing", "ambiguous", "baseline"]
    candidates: list[SourceRef] = Field(default_factory=list)


class CrossFieldResult(BaseModel):
    name: str
    baseline_value: str | None = None
    values: list[FieldValue]


class CrossDocumentResult(BaseModel):
    baseline_id: int
    fields: list[CrossFieldResult]
    export_signature: str | None = None
