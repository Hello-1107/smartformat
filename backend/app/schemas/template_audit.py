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
    data_type: Literal["text", "number", "date", "id_number", "phone"] = "text"
    check_format: bool = True
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
    data_type: Literal["text", "number", "date", "id_number", "phone"]
    check_format: bool


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


class TemplateIssue(BaseModel):
    category: Literal["结构", "固定内容", "必填", "字段规范", "格式", "页面", "表格"]
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


class TemplateReviewOut(TemplateReviewResult):
    template_snapshot: dict | None = None
    id: int
    workspace_id: int
    template_id: int
    template_version: int
    document_id: int
    created_at: datetime
