"""文档及其解析结构 schema。

ParsedDocument 由 services/docx_parser.py 产出，字段与规则引擎消费口径一致。
"""

from datetime import datetime

from pydantic import BaseModel, Field

PARSER_VERSION = 4


class FontInfo(BaseModel):
    name: str | None = None
    ascii_name: str | None = None
    size: float | None = None
    bold: bool | None = None
    italic: bool | None = None
    color: str | None = None


class ParsedParagraph(BaseModel):
    index: int
    text: str
    style_name: str
    level: int | None = None  # 1..6 表示标题层级，None 表示正文
    is_title: bool = False
    runs: list["ParsedRun"] = Field(default_factory=list)
    font: FontInfo = FontInfo()
    alignment: str | None = None
    line_spacing: float | None = None
    line_spacing_kind: str = "multiple"
    space_before: float | None = None
    space_after: float | None = None
    first_line_indent_chars: float | None = None
    numbered: bool = False
    bullet: bool = False


class ParsedRun(BaseModel):
    text: str
    font: FontInfo = Field(default_factory=FontInfo)


class ParsedSection(BaseModel):
    index: int
    paper: str | None = None
    width_cm: float | None = None
    height_cm: float | None = None
    margin_top_cm: float | None = None
    margin_bottom_cm: float | None = None
    margin_left_cm: float | None = None
    margin_right_cm: float | None = None
    header_distance_cm: float | None = None
    footer_distance_cm: float | None = None


class ParsedDocument(BaseModel):
    parser_version: int = PARSER_VERSION
    filename: str
    sections: list[ParsedSection] = []
    paragraphs: list[ParsedParagraph] = []


class DocumentOut(BaseModel):
    id: int
    workspace_id: int
    filename: str
    size: int
    created_at: datetime
    file_type: str = "docx"
    pdf_page_map: list[int] | None = None
    pdf_ocr_pages: list[int] | None = None

    model_config = {"from_attributes": True}


class DocumentDetail(DocumentOut):
    parsed: ParsedDocument | None = None
