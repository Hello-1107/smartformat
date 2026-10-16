"""填写样例模板的确定性提取与审查。

模板中的个人信息不会被当成标准答案。只有用户在配置页明确标记为 ``fixed`` 的
区域才比较文字；``variable`` 区域只检查必填、字段类型和所选格式。
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.text.paragraph import Paragraph

from app.schemas.check import Violation
from app.schemas.document import FontInfo
from app.schemas.template_audit import (
    TemplateBlock,
    TemplateConfiguration,
    TemplateIssue,
    TemplateParagraphFormat,
    TemplateReviewResult,
)
from app.services.checker import _bool_match, _color_match, _fonts_equal, _num_close
from app.services.document_content import _paragraphs
from app.services.docx_parser import (
    _dominant_run,
    _first_line_indent_chars,
    _heading_level,
    _line_spacing_multiple,
    _paragraph_effective_bold_italic,
    _paragraph_alignment,
    _parse_section,
    _run_font,
)
from app.services.revision_copy import is_repairable_format


def _paragraph_format(paragraph: Paragraph) -> TemplateParagraphFormat:
    run = _dominant_run(paragraph)
    font = _run_font(run, paragraph) if run is not None else FontInfo()
    font = _paragraph_effective_bold_italic(paragraph, font)
    pf = paragraph.paragraph_format
    return TemplateParagraphFormat(
        font=font,
        alignment=_paragraph_alignment(paragraph),
        line_spacing=_line_spacing_multiple(pf),
        space_before=round(pf.space_before.pt, 2) if pf.space_before is not None else None,
        space_after=round(pf.space_after.pt, 2) if pf.space_after is not None else None,
        first_line_indent_chars=_first_line_indent_chars(paragraph, font.size),
    )


def _default_mode(paragraph: Paragraph, text: str, *, first_row: bool) -> str:
    if not text.strip():
        return "ignore"
    if first_row or _heading_level(paragraph) is not None:
        return "fixed"
    if len(text.strip()) <= 50 and text.rstrip().endswith(("：", ":")):
        return "fixed"
    if _paragraph_alignment(paragraph) is not None and len(text.strip()) <= 40:
        return "fixed"
    return "variable"


def extract_template_configuration(path: str | Path) -> TemplateConfiguration:
    doc = Document(str(path))
    root = doc.element
    body = root.body
    all_paragraphs = _paragraphs(root)
    top_paragraphs = list(root.xpath("./w:body/w:p"))
    top_tables = list(root.xpath("./w:body/w:tbl"))
    top_paths = {element.getroottree().getpath(element): index for index, element in enumerate(top_paragraphs)}
    table_paths = {element.getroottree().getpath(element): index for index, element in enumerate(top_tables)}
    table_shapes = [
        [len(row.xpath("./w:tc")) for row in table.xpath("./w:tr")]
        for table in top_tables
    ]

    blocks: list[TemplateBlock] = []
    for content_index, element in enumerate(all_paragraphs):
        paragraph = Paragraph(element, doc)
        text = paragraph.text or ""
        path = element.getroottree().getpath(element)
        top_index = top_paths.get(path)
        table_index = row_index = column_index = paragraph_in_cell = None
        kind = "paragraph"
        location = f"正文段落 {top_index + 1}" if top_index is not None else "文档区域"
        block_id = f"p:{top_index}" if top_index is not None else f"content:{content_index}"
        first_row = False

        if top_index is None:
            outer_table = next(
                (ancestor for ancestor in element.xpath("ancestor::w:tbl") if ancestor.getparent() is body),
                None,
            )
            if outer_table is not None:
                table_index = table_paths.get(outer_table.getroottree().getpath(outer_table))
                rows = list(outer_table.xpath("./w:tr"))
                row = next((item for item in element.xpath("ancestor::w:tr") if item in rows), None)
                if row is not None:
                    row_index = rows.index(row)
                    cells = list(row.xpath("./w:tc"))
                    cell = next((item for item in element.xpath("ancestor::w:tc") if item in cells), None)
                    if cell is not None:
                        column_index = cells.index(cell)
                        cell_paragraphs = list(cell.xpath(".//w:p[not(ancestor::w:txbxContent) and not(ancestor::w:del)]"))
                        paragraph_in_cell = next(
                            (idx for idx, item in enumerate(cell_paragraphs) if item is element), 0
                        )
                if None not in (table_index, row_index, column_index, paragraph_in_cell):
                    kind = "table_cell"
                    first_row = row_index == 0
                    block_id = f"t:{table_index}:r:{row_index}:c:{column_index}:p:{paragraph_in_cell}"
                    location = f"表格 {table_index + 1}，第 {row_index + 1} 行第 {column_index + 1} 列"

        mode = _default_mode(paragraph, text, first_row=first_row)
        blocks.append(
            TemplateBlock(
                id=block_id,
                order=content_index,
                kind=kind,
                location=location,
                content_index=content_index,
                top_level_paragraph_index=top_index,
                table_index=table_index,
                row_index=row_index,
                column_index=column_index,
                paragraph_in_cell=paragraph_in_cell,
                text=text,
                label=text.strip()[:40] or location,
                mode=mode,
                required=bool(text.strip()) and mode != "ignore",
                data_type="text",
                check_format=bool(text.strip()),
                format=_paragraph_format(paragraph),
            )
        )

    page = _parse_section(doc.sections[0], 0) if doc.sections else None
    return TemplateConfiguration(page=page, table_shapes=table_shapes, blocks=blocks)


def _normal_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _valid_data_type(value: str, data_type: str) -> bool:
    text = value.strip()
    if data_type == "text":
        return True
    if data_type == "number":
        return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text))
    if data_type == "date":
        return bool(re.fullmatch(r"\d{4}(?:年|[-/.])\d{1,2}(?:月|[-/.])\d{1,2}日?", text))
    if data_type == "id_number":
        return bool(re.fullmatch(r"(?:\d{15}|\d{17}[\dXx])", text))
    if data_type == "phone":
        compact = re.sub(r"[\s()-]", "", text)
        return bool(re.fullmatch(r"\+?\d{7,15}", compact))
    return True


def _display_data_type(data_type: str) -> str:
    return {
        "text": "文本", "number": "数字", "date": "日期",
        "id_number": "身份证号", "phone": "电话号码",
    }.get(data_type, data_type)


def _format_differences(expected: TemplateParagraphFormat, actual: TemplateParagraphFormat) -> list[tuple[str, str, object, object]]:
    pairs: list[tuple[str, str, object, object]] = []
    font_fields = (
        ("name", "中文字体", expected.font.name, actual.font.name, _fonts_equal),
        ("ascii_name", "西文字体", expected.font.ascii_name, actual.font.ascii_name, _fonts_equal),
        ("size", "字号", expected.font.size, actual.font.size, lambda a, e: _num_close(a, e, 0.5)),
        ("bold", "加粗", expected.font.bold, actual.font.bold, _bool_match),
        ("italic", "斜体", expected.font.italic, actual.font.italic, _bool_match),
        ("color", "字体颜色", expected.font.color, actual.font.color, _color_match),
    )
    for field, label, wanted, got, compare in font_fields:
        if wanted is not None and not compare(got, wanted):
            pairs.append(("font", field, wanted, got))
    paragraph_fields = (
        ("alignment", expected.alignment, actual.alignment, lambda a, e: a == e),
        ("line_spacing", expected.line_spacing, actual.line_spacing, lambda a, e: _num_close(a, e, 0.08)),
        ("space_before", expected.space_before, actual.space_before, lambda a, e: _num_close(a, e, 0.5)),
        ("space_after", expected.space_after, actual.space_after, lambda a, e: _num_close(a, e, 0.5)),
        ("first_line_indent_chars", expected.first_line_indent_chars, actual.first_line_indent_chars, lambda a, e: _num_close(a, e, 0.15)),
    )
    for field, wanted, got, compare in paragraph_fields:
        if wanted is not None and not compare(got, wanted):
            pairs.append(("paragraph", field, wanted, got))
    return pairs


def _page_differences(expected, actual) -> list[tuple[str, object, object]]:
    fields = (
        ("paper", 0), ("width_cm", 0.2), ("height_cm", 0.2),
        ("margin_top_cm", 0.2), ("margin_bottom_cm", 0.2),
        ("margin_left_cm", 0.2), ("margin_right_cm", 0.2),
        ("header_distance_cm", 0.2), ("footer_distance_cm", 0.2),
    )
    result = []
    for field, tolerance in fields:
        wanted, got = getattr(expected, field), getattr(actual, field)
        if wanted is None:
            continue
        equal = got == wanted if not tolerance else _num_close(got, wanted, tolerance)
        if not equal:
            result.append((field, wanted, got))
    return result


def review_against_template(template: TemplateConfiguration, document_path: str | Path) -> TemplateReviewResult:
    target = extract_template_configuration(document_path)
    target_by_id = {block.id: block for block in target.blocks}
    issues: list[TemplateIssue] = []

    template_paragraph_count = sum(block.top_level_paragraph_index is not None for block in template.blocks)
    target_paragraph_count = sum(block.top_level_paragraph_index is not None for block in target.blocks)
    if template_paragraph_count != target_paragraph_count:
        issues.append(TemplateIssue(
            category="结构", severity="错误", message="正文段落数量与模板不一致，可能存在缺失或多余章节",
            expected=template_paragraph_count, actual=target_paragraph_count,
        ))

    if template.table_shapes != target.table_shapes:
        issues.append(TemplateIssue(
            category="表格", severity="错误", message="表格数量、行数或列数与模板不一致",
            expected=template.table_shapes, actual=target.table_shapes,
        ))

    for block in template.blocks:
        if block.mode == "ignore":
            continue
        actual = target_by_id.get(block.id)
        value = actual.text if actual is not None else ""
        if block.required and not value.strip():
            issues.append(TemplateIssue(
                category="必填", severity="错误", message=f"{block.label or block.location}为必填区域，但待审文档为空或缺失",
                template_block_id=block.id, template_content_index=block.content_index,
                document_content_index=actual.content_index if actual else None,
                expected="必填", actual=value or None,
            ))
            continue
        if actual is None:
            issues.append(TemplateIssue(
                category="结构", severity="错误", message=f"待审文档缺少模板区域：{block.location}",
                template_block_id=block.id, template_content_index=block.content_index,
            ))
            continue
        if block.mode == "fixed" and _normal_text(block.text) != _normal_text(value):
            issues.append(TemplateIssue(
                category="固定内容", severity="错误", message=f"{block.label or block.location}应与模板固定文字一致",
                template_block_id=block.id, template_content_index=block.content_index,
                document_content_index=actual.content_index, expected=block.text, actual=value,
                quote=value or None, recommended_replacement=block.text,
                repairable=bool(value),
            ))
        elif block.mode == "variable" and value.strip() and not _valid_data_type(value, block.data_type):
            issues.append(TemplateIssue(
                category="字段规范", severity="错误",
                message=f"{block.label or block.location}应填写为{_display_data_type(block.data_type)}",
                template_block_id=block.id, template_content_index=block.content_index,
                document_content_index=actual.content_index, expected=_display_data_type(block.data_type),
                actual=value, quote=value, repairable=True,
            ))
        if block.check_format and value.strip():
            for category, field, wanted, got in _format_differences(block.format, actual.format):
                violation = Violation(
                    scope="template", category=category, field=field, expected=wanted, actual=got,
                    message=f"{block.label or block.location}的{field}应与模板一致",
                    paragraph_index=actual.top_level_paragraph_index, paragraph_text=value,
                )
                issues.append(TemplateIssue(
                    category="格式", severity="警告", message=violation.message,
                    template_block_id=block.id, template_content_index=block.content_index,
                    document_content_index=actual.content_index, expected=wanted, actual=got,
                    repairable=is_repairable_format(violation) and actual.top_level_paragraph_index is not None,
                    format_violation=violation,
                ))

    if template.check_page and template.page is not None and target.page is not None:
        for field, wanted, got in _page_differences(template.page, target.page):
            violation = Violation(
                scope="page", category="page", field=field, expected=wanted, actual=got,
                message=f"页面字段 {field} 应与模板一致",
            )
            issues.append(TemplateIssue(
                category="页面", severity="警告", message=violation.message,
                expected=wanted, actual=got, repairable=is_repairable_format(violation),
                format_violation=violation,
            ))

    repairable = sum(1 for issue in issues if issue.repairable)
    total = len(issues)
    return TemplateReviewResult(
        summary="模板审查通过" if not issues else f"共发现 {total} 项模板差异，其中 {repairable} 项可在确认后修订",
        issues=issues,
        total=total,
        repairable=repairable,
        compliant=not issues,
    )
