"""从 Word 文本模板提取格式规则的离线测试。"""

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from app.services.checker import run_check
from app.services.document_rule_extractor import extract_ruleset_from_document
from app.services.docx_parser import parse_docx


def _font(paragraph, name: str, size: float, bold: bool = False) -> None:
    run = paragraph.runs[0]
    run.font.size = Pt(size)
    run.font.bold = bold
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)


def _template_bytes(body_size: float = 12) -> bytes:
    doc = Document()
    doc.sections[0].page_width = Cm(21)
    doc.sections[0].page_height = Cm(29.7)
    title = doc.add_heading("1 总标题", level=1)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    _font(title, "黑体", 18, True)

    second = doc.add_heading("1.1 二级标题", level=2)
    second.alignment = WD_ALIGN_PARAGRAPH.LEFT
    _font(second, "黑体", 16, True)

    third = doc.add_heading("1.1.1 三级标题", level=3)
    _font(third, "楷体", 14, False)

    for text in ("第一段正文。", "第二段正文。"):
        paragraph = doc.add_paragraph(text)
        paragraph.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
        paragraph.paragraph_format.line_spacing = 1.5
        _font(paragraph, "宋体", body_size)

    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def test_extracts_heading_body_and_page_rules(tmp_path) -> None:
    path = tmp_path / "标准文本模板.docx"
    path.write_bytes(_template_bytes())

    ruleset = extract_ruleset_from_document(path)

    assert ruleset.name == "标准文本模板"
    assert ruleset.body is not None
    assert ruleset.body.font is not None
    assert ruleset.body.font.name == "宋体"
    assert ruleset.body.font.size == 12
    assert ruleset.body.paragraph is not None
    assert ruleset.body.paragraph.alignment == "justify"
    assert ruleset.body.paragraph.line_spacing == 1.5
    assert ruleset.headings is not None
    assert set(ruleset.headings) == {"h1", "h2", "h3"}
    assert ruleset.headings["h1"].font.size == 18
    assert ruleset.headings["h2"].font.size == 16
    assert ruleset.headings["h3"].font.name == "楷体"
    assert ruleset.heading_structure is not None
    assert ruleset.heading_structure.max_level == 3
    assert ruleset.heading_structure.require_numbered is True
    assert ruleset.page is not None
    assert ruleset.page.paper == "A4"

    target = tmp_path / "待审.docx"
    target.write_bytes(_template_bytes(body_size=14))
    violations, summary = run_check(parse_docx(target), ruleset)
    assert summary.compliant is False
    assert any(
        issue.scope == "body" and issue.field == "size" and issue.expected == 12
        for issue in violations
    )


def test_document_template_endpoint_creates_editable_rule(client, auth, workspace) -> None:
    headers, _ = auth
    response = client.post(
        "/api/rules/from-document-template",
        params={
            "workspace_id": workspace,
            "filename": "标准文本模板.docx",
            "name": "团队文稿规范",
        },
        content=_template_bytes(),
        headers={**headers, "Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 201, response.text
    rule = response.json()
    assert rule["name"] == "团队文稿规范"
    assert rule["natural_language"] == "从文本模板提取：标准文本模板.docx"
    assert rule["ruleset"]["body"]["font"]["size"] == 12
    assert set(rule["ruleset"]["headings"]) == {"h1", "h2", "h3"}

    versions = client.get(f"/api/rules/{rule['id']}/versions", headers=headers)
    assert versions.status_code == 200
    assert len(versions.json()) == 1


def test_document_template_rejects_empty_document(client, auth, workspace) -> None:
    headers, _ = auth
    empty = Document()
    stream = io.BytesIO()
    empty.save(stream)
    response = client.post(
        "/api/rules/from-document-template",
        params={"workspace_id": workspace, "filename": "empty.docx"},
        content=stream.getvalue(),
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 422
    assert "没有可用于提取格式" in response.json()["detail"]
