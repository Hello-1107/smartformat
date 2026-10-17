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


_FORM_FIELD_LABELS = {
    "序号", "姓名", "性别", "年龄", "民族", "政治面貌", "出生日期", "出生年月",
    "身份证号", "证件号码", "学号", "班级", "专业", "学院", "学校", "学历", "学位",
    "籍贯", "户籍所在地", "家庭住址", "现住址", "地址", "邮政编码", "联系电话", "手机号码",
    "手机号", "电话", "邮箱", "电子邮箱", "单位", "工作单位", "部门", "职务", "岗位",
    "关系", "称谓", "成员姓名", "家庭成员", "申请人", "负责人", "填表日期", "日期", "备注",
    "申请理由", "主要经历", "个人简介", "审核意见", "审批意见", "签名", "签字",
}


def _field_label(text: str) -> str | None:
    value = re.sub(r"\s+", "", text).strip("：:")
    value = re.sub(r"[（(][^）)]*[）)]$", "", value)
    return value if value in _FORM_FIELD_LABELS else None


def _field_data_type(label: str | None) -> str:
    if not label:
        return "text"
    if label in {"年龄", "序号", "邮政编码"}:
        return "number"
    if "日期" in label or "年月" in label:
        return "date"
    if label in {"身份证号", "证件号码"}:
        return "id_number"
    if label in {"联系电话", "手机号码", "手机号", "电话"}:
        return "phone"
    return "text"


def _classify_table_fields(blocks: list[TemplateBlock]) -> None:
    """把表格字段名与样例值分开，避免把张三、20 岁等样例当成固定答案。"""
    table_blocks = [
        block for block in blocks
        if block.kind == "table_cell" and None not in (block.table_index, block.row_index, block.column_index)
    ]
    primary_text: dict[tuple[int, int, int], str] = {}
    for block in table_blocks:
        key = (block.table_index, block.row_index, block.column_index)
        if block.text.strip() and key not in primary_text:
            primary_text[key] = block.text.strip()

    known_labels = {key: _field_label(text) for key, text in primary_text.items()}
    row_has_labels = {
        (table, row)
        for (table, row, _column), label in known_labels.items()
        if label is not None
    }

    for block in table_blocks:
        if not block.text.strip():
            block.mode = "ignore"
            block.required = False
            block.check_format = False
            continue
        assert block.table_index is not None and block.row_index is not None and block.column_index is not None
        key = (block.table_index, block.row_index, block.column_index)
        own_label = known_labels.get(key)
        if own_label:
            block.label = own_label
            block.mode = "fixed"
            block.required = True
            block.data_type = "text"
            continue

        previous_label = known_labels.get((block.table_index, block.row_index, block.column_index - 1))
        header_text = primary_text.get((block.table_index, 0, block.column_index))
        header_label = known_labels.get((block.table_index, 0, block.column_index))
        if previous_label or (block.row_index > 0 and header_text):
            label = previous_label or header_label or header_text
            block.label = str(label)
            block.mode = "variable"
            block.required = True
            block.data_type = _field_data_type(previous_label or header_label)
        elif (block.table_index, block.row_index) in row_has_labels:
            block.mode = "variable"
            block.required = True
            block.data_type = "text"
        elif block.row_index == 0:
            # 无常见字段名时仍按普通表头处理，后续数据行会继承该列名称。
            block.label = block.text.strip()[:40]
            block.mode = "fixed"
            block.required = True
            block.data_type = "text"
        else:
            block.mode = "variable"
            block.required = True
            block.data_type = "text"


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

    _classify_table_fields(blocks)
    page = _parse_section(doc.sections[0], 0) if doc.sections else None
    return TemplateConfiguration(page=page, table_shapes=table_shapes, blocks=blocks)


def _normal_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _valid_data_type(value: str, data_type: str) -> bool:
    text = value.strip()
    if data_type == "text":
        return True
    if data_type == "number":
        return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:岁)?", text))
    if data_type == "date":
        return bool(re.fullmatch(
            r"(?:\d{4}年\d{1,2}月(?:\d{1,2}日)?|\d{4}[-/.]\d{1,2}(?:[-/.]\d{1,2})?)",
            text,
        ))
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
        summary="表单模板审查通过" if not issues else f"共发现 {total} 项模板差异，其中 {repairable} 项可在确认后修订",
        issues=issues,
        total=total,
        repairable=repairable,
        compliant=not issues,
    )
