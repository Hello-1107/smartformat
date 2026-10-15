"""审查规则 schema —— 系统核心契约。

RuleSet 是「自然语言格式要求」与「确定性规则引擎」之间的结构化中间层：
- DeepSeek 只负责把自然语言转成符合此 schema 的 JSON（见 services/deepseek_spec.py）。
- 规则引擎（services/checker.py）严格按此 schema 的字段对 docx 逐项核对。
- 字段为 None 表示「该项不约束」，引擎会跳过。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, field_validator

HeadingKey = Literal["h1", "h2", "h3", "h4", "h5", "h6"]


class FontRule(BaseModel):
    """字体约束：name 指中文字体，ascii_name 指西文字体。"""

    name: str | None = None
    ascii_name: str | None = None
    size: float | None = Field(default=None, description="字号，单位 pt")
    bold: bool | None = None
    italic: bool | None = None
    color: str | None = Field(default=None, description="十六进制 RGB，如 000000")


class ParagraphRule(BaseModel):
    """段落约束。"""

    alignment: Literal["left", "center", "right", "justify"] | None = None
    line_spacing: float | None = Field(default=None, description="行距倍数，如 1.5")
    space_before: float | None = Field(default=None, description="段前间距，单位 pt")
    space_after: float | None = Field(default=None, description="段后间距，单位 pt")
    first_line_indent_chars: float | None = Field(
        default=None, description="首行缩进，单位：字符数"
    )
    numbered: bool | None = None
    bullet: bool | None = None


class PageRule(BaseModel):
    """页面约束。"""

    paper: str | None = Field(default=None, description="纸张类型，如 A4")
    width_cm: float | None = None
    height_cm: float | None = None
    margin_top_cm: float | None = None
    margin_bottom_cm: float | None = None
    margin_left_cm: float | None = None
    margin_right_cm: float | None = None
    header_distance_cm: float | None = None
    footer_distance_cm: float | None = None


class ScopeRule(BaseModel):
    """某一作用域（正文 / 某级标题）的约束。"""

    font: FontRule | None = None
    paragraph: ParagraphRule | None = None


class HeadingStructureRule(BaseModel):
    """标题层级结构约束。"""

    max_level: int | None = Field(default=None, description="允许的最大标题层级，1..6")
    require_numbered: bool | None = Field(
        default=None, description="标题是否必须带编号（如 1. / 1.1）"
    )


class RuleSet(BaseModel):
    name: str
    description: str | None = None
    body: ScopeRule | None = None
    headings: dict[HeadingKey, ScopeRule] | None = None
    page: PageRule | None = None
    heading_structure: HeadingStructureRule | None = None


class RuleCreate(BaseModel):
    workspace_id: int
    natural_language: str = Field(min_length=1)
    name: str | None = None


class RuleOut(BaseModel):
    id: int
    workspace_id: int
    name: str
    natural_language: str
    ruleset: RuleSet
    created_at: datetime

    model_config = {"from_attributes": True}


class RuleTemplateOut(BaseModel):
    """系统内置或当前工作区内可直接套用的规则模板。"""

    id: str
    name: str
    description: str
    ruleset: RuleSet
    source: Literal["system", "workspace"] = "system"


class RuleTemplateCreate(BaseModel):
    """从当前已配置的规则集保存一份可复用的工作区模板。"""

    workspace_id: int
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default="", max_length=1000)
    ruleset: RuleSet

    @field_validator("name")
    @classmethod
    def name_must_not_be_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("模板名称不能为空")
        return value


class RuleFromTemplateCreate(BaseModel):
    workspace_id: int
    template_id: str
    name: str | None = Field(default=None, max_length=200)


class RuleRevisionOut(BaseModel):
    """规则每次保存后的不可变快照。"""

    id: int
    rule_id: int
    version: int
    name: str
    natural_language: str
    ruleset: RuleSet
    created_at: datetime

    model_config = {"from_attributes": True}
