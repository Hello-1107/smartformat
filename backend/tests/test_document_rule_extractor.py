"""从 Word 文本模板提取格式规则的离线测试。"""

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from app.services.checker import run_check
from app.services.document_rule_extractor import extract_candidates, extract_ruleset_from_document
from app.services.docx_parser import parse_docx
from app.services.revision_copy import build_revised_copy


def _font(paragraph, name: str, size: float, bold: bool = False) -> None:
    run = paragraph.runs[0]
    run.font.size = Pt(size)
    run.font.bold = bold
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)


def test_extracted_zero_spacing_is_unrestricted_but_nonzero_is_preserved(tmp_path) -> None:
    template = Document()
    template.sections[0].header_distance = Cm(0)
    paragraph = template.add_paragraph("这里是足够长的正文样例，用来验证模板提取的零值不会成为检查限制。")
    paragraph.paragraph_format.space_before = Pt(12)
    paragraph.paragraph_format.space_after = Pt(0)
    paragraph.paragraph_format.first_line_indent = Pt(0)
    path = tmp_path / "零值模板.docx"
    template.save(path)

    extraction = extract_candidates(path)
    style = extraction.candidates["body"][0].style.paragraph
    assert style is not None
    assert style.space_before == 12
    assert style.space_after is None
    assert style.first_line_indent_chars is None
    assert extraction.ruleset.page is not None
    assert extraction.ruleset.page.header_distance_cm is None


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


def test_structured_template_extracts_regions_and_checks_within_section(tmp_path) -> None:
    template = Document()
    first = template.add_heading("第1章 项目概述", level=1)
    _font(first, "黑体", 18, True)
    body = template.add_paragraph("这里是项目概述的标准正文示例。")
    _font(body, "宋体", 12)
    second = template.add_heading("第2章 项目实现", level=1)
    _font(second, "黑体", 18, True)
    body = template.add_paragraph("这里是项目实现的标准正文示例。")
    _font(body, "宋体", 12)
    template_path = tmp_path / "结构模板.docx"
    template.save(template_path)

    extraction = extract_candidates(template_path)
    assert [region.anchor for region in extraction.regions] == ["第1章 项目概述", "第2章 项目实现"]
    assert all(region.body_style and region.body_style.font.size == 12 for region in extraction.regions)

    target = Document()
    first = target.add_heading("第1章 项目概述", level=1)
    _font(first, "黑体", 18, True)
    body = target.add_paragraph("待审文档中的项目概述正文内容已经替换。")
    _font(body, "宋体", 14)
    second = target.add_heading("自定义实现说明", level=1)
    _font(second, "黑体", 18, True)
    body = target.add_paragraph("待审文档中的项目实现正文内容已经替换。")
    _font(body, "宋体", 12)
    target_path = tmp_path / "待审报告.docx"
    target.save(target_path)

    ruleset = extraction.ruleset.model_copy(update={"template_regions": extraction.regions})
    violations, _ = run_check(parse_docx(target_path), ruleset)
    assert any(issue.scope.startswith("template_region:第1章") and issue.field == "size" for issue in violations)
    assert any(issue.field == "missing_region" and issue.expected == "第2章 项目实现" for issue in violations)
    assert any(issue.field == "extra_region" and issue.actual == "自定义实现说明" for issue in violations)

    variable = [region.model_copy() for region in extraction.regions]
    variable[1].mode = "variable"
    variable_rules = extraction.ruleset.model_copy(update={"template_regions": variable})
    variable_issues, _ = run_check(parse_docx(target_path), variable_rules)
    assert not any(issue.field in {"missing_region", "extra_region"} for issue in variable_issues)

    variable[0].mode = "ignore"
    ignored_rules = extraction.ruleset.model_copy(update={"template_regions": variable})
    ignored_issues, _ = run_check(parse_docx(target_path), ignored_rules)
    assert not any(issue.scope.startswith("template_region:第1章") for issue in ignored_issues)


def test_second_phase_checks_toc_captions_code_and_repairs_anchor(tmp_path) -> None:
    template = Document()
    template.styles.add_style("TOC 1", WD_STYLE_TYPE.PARAGRAPH)
    template.styles.add_style("Code Block", WD_STYLE_TYPE.PARAGRAPH)
    template.add_paragraph("第1章 项目概述\t1", style="TOC 1")
    heading = template.add_heading("第1章 项目概述", level=1)
    _font(heading, "黑体", 18, True)
    code = template.add_paragraph("const answer = 42;", style="Code Block")
    _font(code, "宋体", 10)
    caption = template.add_paragraph("图1 系统架构")
    _font(caption, "宋体", 10)
    template.add_paragraph("Spring Boot 与 Vue 用于实现前后端分离的课程项目说明。")
    template_path = tmp_path / "二期模板.docx"
    template.save(template_path)

    extraction = extract_candidates(template_path)
    assert [p.role for p in parse_docx(template_path).paragraphs] == [
        "toc", "heading", "code", "figure_caption", "body",
    ]
    assert extraction.ruleset.template_checks is not None
    assert extraction.ruleset.template_checks.check_toc
    assert extraction.ruleset.template_checks.check_figure_numbering
    assert extraction.ruleset.template_checks.check_code_style
    assert extraction.ruleset.template_checks.toc_entries == ["第1章 项目概述"]

    target = Document()
    target.styles.add_style("TOC 1", WD_STYLE_TYPE.PARAGRAPH)
    target.styles.add_style("Code Block", WD_STYLE_TYPE.PARAGRAPH)
    target.add_paragraph("不存在的章节\t1", style="TOC 1")
    heading = target.add_heading("项目概述", level=1)
    _font(heading, "黑体", 18, True)
    code = target.add_paragraph("const answer = 42;", style="Code Block")
    _font(code, "宋体", 12)
    target.add_paragraph("图1 系统架构")
    target.add_paragraph("图3 运行结果")
    target_path = tmp_path / "二期待审.docx"
    target.save(target_path)

    ruleset = extraction.ruleset.model_copy(update={"template_regions": extraction.regions})
    violations, _ = run_check(parse_docx(target_path), ruleset)
    assert any(issue.field == "toc_entry_missing" for issue in violations)
    assert any(issue.field == "toc_without_heading" for issue in violations)
    assert any(issue.field == "caption_number_gap" for issue in violations)
    assert any(issue.scope == "代码块" and issue.field == "size" for issue in violations)
    without_figures = ruleset.model_copy(deep=True)
    without_figures.template_checks.check_figure_numbering = False
    disabled_issues, _ = run_check(parse_docx(target_path), without_figures)
    assert not any(issue.category == "caption" or issue.scope == "图题注" for issue in disabled_issues)
    anchor_issue = next(issue for issue in violations if issue.field == "anchor_text")
    revised = Document(io.BytesIO(build_revised_copy(target_path, "二期待审.docx", [anchor_issue], [])))
    assert revised.paragraphs[1].text == "第1章 项目概述"
