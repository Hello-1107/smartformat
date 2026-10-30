"""上传填写样例后进行确定性模板审查的接口契约。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator

from app.schemas.check import Violation
from app.schemas.document import FontInfo, ParsedSection


class TemplateParagraphFormat(BaseModel):
    font: FontInfo = Field(default_factory=FontInfo)
    fonts: list[FontInfo] = Field(default_factory=list)
    alignment: str | None = None
    line_spacing: float | None = None
    line_spacing_kind: str = "multiple"
    space_before: float | None = None
    space_after: float | None = None
    first_line_indent_chars: float | None = None


class TemplateFieldRule(BaseModel):
    kind: Literal["email", "length", "chinese_length", "number_range", "allowed_values", "contains", "same_as", "exact_text", "forbidden_value", "number_with_unit"]
    min_value: float | None = Field(default=None, allow_inf_nan=False)
    max_value: float | None = Field(default=None, allow_inf_nan=False)
    min_length: int | None = Field(default=None, ge=0, le=10000)
    max_length: int | None = Field(default=None, ge=0, le=10000)
    options: list[str] = Field(default_factory=list, max_length=30)
    text: str = Field(default="", max_length=200)
    replacement_text: str = Field(default="", max_length=200)
    other_block_id: str = Field(default="", max_length=100)

    @model_validator(mode="after")
    def valid_parameters(self):
        if self.kind in {"length", "chinese_length"} and (self.min_length is None and self.max_length is None or
                                      self.min_length is not None and self.max_length is not None and self.min_length > self.max_length):
            raise ValueError("长度规则需要有效的最小或最大长度")
        if self.kind == "number_range" and (self.min_value is None and self.max_value is None or
                                            self.min_value is not None and self.max_value is not None and self.min_value > self.max_value):
            raise ValueError("数值范围规则需要有效的最小或最大值")
        if self.kind == "allowed_values" and (not self.options or any(not value.strip() for value in self.options)):
            raise ValueError("可选值规则不能为空")
        if self.kind == "allowed_values":
            self.options = [value.strip() for value in self.options]
            if any(len(value) > 100 for value in self.options):
                raise ValueError("单个可选值不能超过 100 字")
        if self.kind in {"contains", "exact_text", "forbidden_value", "number_with_unit"} and not self.text.strip():
            raise ValueError("文字或单位规则不能为空")
        if self.kind == "number_with_unit" and (len(self.text.strip()) > 10 or not self.text.strip().isalpha()):
            raise ValueError("单位必须为 1–10 个文字字符")
        if self.kind == "same_as" and not self.other_block_id:
            raise ValueError("一致性规则必须指定另一字段")
        return self


class TemplateRequirementDraftRequest(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class TemplateRequirementDraftResult(BaseModel):
    rules: list[TemplateFieldRule] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)
    required: bool | None = None


class TemplateBlock(BaseModel):
    id: str
    order: int = Field(ge=0)
    kind: Literal["paragraph", "table_cell"]
    location: str
    content_index: int = Field(ge=0)
    top_level_paragraph_index: int | None = Field(default=None, ge=0)
    table_index: int | None = Field(default=None, ge=0)
    row_index: int | None = Field(default=None, ge=0)
    column_index: int | None = Field(default=None, ge=0)
    paragraph_in_cell: int | None = Field(default=None, ge=0)
    text: str = ""
    label: str = Field(default="", max_length=100)
    mode: Literal["fixed", "variable", "ignore"] = "variable"
    required: bool = True
    data_type: Literal["text", "number", "date", "id_number", "phone", "email"] = "text"
    check_format: bool = True
    recognition_confidence: Literal["high", "medium", "low"] = "medium"
    recognition_note: str = ""
    recognition_confirmed: bool = False
    rules: list[TemplateFieldRule] = Field(default_factory=list, max_length=20)
    requirement_text: str = Field(default="", max_length=1000)
    unsupported_requirements: list[str] = Field(default_factory=list, max_length=20)
    format: TemplateParagraphFormat = Field(default_factory=TemplateParagraphFormat)


class TemplateConfiguration(BaseModel):
    check_page: bool = True
    page: ParsedSection | None = None
    table_shapes: list[list[int]] = Field(default_factory=list)
    blocks: list[TemplateBlock] = Field(default_factory=list, max_length=1500)


class DocumentTemplateOut(BaseModel):
    id: int
    workspace_id: int
    version: int
    name: str
    filename: str
    size: int
    is_active: bool
    is_published: bool
    is_review_active: bool = False
    config: TemplateConfiguration
    created_at: datetime


class TemplateBlockUpdate(BaseModel):
    id: str
    label: str = Field(default="", max_length=100)
    mode: Literal["fixed", "variable", "ignore"]
    required: bool
    data_type: Literal["text", "number", "date", "id_number", "phone", "email"]
    check_format: bool
    recognition_confirmed: bool = False
    rules: list[TemplateFieldRule] | None = Field(default=None, max_length=20)
    requirement_text: str = Field(default="", max_length=1000)
    unsupported_requirements: list[str] = Field(default_factory=list, max_length=20)


class TemplateConfigurationUpdate(BaseModel):
    workspace_id: int
    template_id: int | None = None
    name: str = Field(min_length=1, max_length=200)
    check_page: bool = True
    blocks: list[TemplateBlockUpdate] = Field(max_length=1500)

    @model_validator(mode="after")
    def unique_blocks(self):
        ids = [block.id for block in self.blocks]
        if len(ids) != len(set(ids)):
            raise ValueError("模板区域不能重复")
        return self


class TemplateReviewCreate(BaseModel):
    workspace_id: int
    document_id: int
    ai_field_ids: list[str] = Field(default_factory=list, max_length=30)

    @model_validator(mode="after")
    def unique_ai_fields(self):
        if len(self.ai_field_ids) != len(set(self.ai_field_ids)):
            raise ValueError("AI 审查字段不能重复")
        return self


class TemplateAiSuggestion(BaseModel):
    block_id: str
    template_content_index: int | None = None
    document_content_index: int | None = None
    quote: str = Field(min_length=1, max_length=2000)
    reason: str = Field(min_length=1, max_length=1000)
    suggestion: str = Field(min_length=1, max_length=2000)
    recommended_replacement: str | None = Field(default=None, max_length=2000)


class TemplateAiReview(BaseModel):
    status: Literal["completed", "failed", "not_configured"]
    summary: str = Field(max_length=1000)
    model: str | None = None
    field_ids: list[str] = Field(default_factory=list)
    suggestions: list[TemplateAiSuggestion] = Field(default_factory=list, max_length=50)


class TemplateIssue(BaseModel):
    category: Literal["结构", "固定内容", "必填", "字段规范", "填写要求", "格式", "页面", "表格"]
    severity: Literal["错误", "警告", "提示"] = "错误"
    message: str
    template_block_id: str | None = None
    template_content_index: int | None = None
    document_content_index: int | None = None
    expected: Any = None
    actual: Any = None
    quote: str | None = None
    recommended_replacement: str | None = None
    repairable: bool = False
    format_violation: Violation | None = None


class TemplateReviewResult(BaseModel):
    summary: str
    issues: list[TemplateIssue] = Field(max_length=1000)
    total: int
    repairable: int
    compliant: bool
    ai_review: TemplateAiReview | None = None


class TemplateReviewOut(TemplateReviewResult):
    template_snapshot: dict | None = None
    id: int
    workspace_id: int
    template_id: int
    template_version: int
    document_id: int
    created_at: datetime
