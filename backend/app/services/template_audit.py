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
    TemplateFieldRule,
    TemplateIssue,
    TemplateParagraphFormat,
    TemplateRequirementDraftResult,
    TemplateReviewResult,
)
from app.services.checker import _bool_match, _color_match, _fonts_equal, _num_close
from app.services.document_content import _paragraphs
from app.services.docx_parser import (
    _dominant_run,
    _first_line_indent_chars,
    _heading_level,
    _is_title,
    _paragraph_alignment,
    _parse_section,
    _run_font,
    _effective_paragraph_value,
    _line_spacing_value,
)
from docx.shared import Length
from docx.enum.text import WD_LINE_SPACING
from app.services.revision_copy import is_repairable_format


_FORM_FIELD_LABELS = {
    "序号", "姓名", "性别", "年龄", "民族", "政治面貌", "出生日期", "出生年月",
    "身份证号", "证件号码", "学号", "班级", "专业", "学院", "学校", "学历", "学位",
    "籍贯", "户籍所在地", "家庭住址", "现住址", "地址", "邮政编码", "联系电话", "手机号码",
    "手机号", "电话", "邮箱", "电子邮箱", "单位", "工作单位", "部门", "职务", "岗位",
    "关系", "称谓", "成员姓名", "家庭成员", "申请人", "负责人", "填表日期", "日期", "备注",
    "申请理由", "主要经历", "个人简介", "审核意见", "审批意见", "签名", "签字",
    "电子邮件", "邮箱地址", "家庭人口数", "家庭人数", "生源类别", "生源地",
}


def _field_label(text: str) -> str | None:
    value = re.sub(r"\s+", "", text).strip("：:")
    value = re.sub(r"[（(][^）)]*[）)]$", "", value)
    return value if value in _FORM_FIELD_LABELS else None


def _field_data_type(label: str | None) -> str:
    if not label:
        return "text"
    if label in {"年龄", "序号", "邮政编码", "家庭人口数", "家庭人数"}:
        return "number"
    if "日期" in label or "年月" in label:
        return "date"
    if label in {"身份证号", "证件号码"}:
        return "id_number"
    if label in {"联系电话", "手机号码", "手机号", "电话"}:
        return "phone"
    if label in {"邮箱", "电子邮箱", "电子邮件", "邮箱地址"}:
        return "email"
    return "text"


def _looks_like_value(text: str) -> bool:
    value = re.sub(r"\s+", "", text).strip()
    return bool(
        not value or len(value) == 1 or "@" in value
        or re.fullmatch(r"[+\-]?\d+(?:\.\d+)?(?:岁|人|元|%|％)?", value)
        or re.fullmatch(r"\d{4}[-/.年]\d{1,2}.*", value)
        or value in {"男", "女", "汉", "群众", "党员", "共青团员", "是", "否"}
    )


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
    # 不靠首行文字给所有数据行命名；仅当标签有明确依据时才自动配对。
    for (table, row, column), text in primary_text.items():
        if known_labels[(table, row, column)] or _looks_like_value(text):
            continue
        following = primary_text.get((table, row, column + 1), "")
        if following and _looks_like_value(following):
            known_labels[(table, row, column)] = text.strip().rstrip("：:")[:40]
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
        own_label = _field_label(block.text)
        if own_label:
            block.label = own_label
            block.mode = "fixed"
            block.required = True
            block.data_type = "text"
            block.recognition_confidence = "high"
            block.recognition_note = "字段名称与已知标签一致"
            continue

        previous_label = known_labels.get((block.table_index, block.row_index, block.column_index - 1))
        header_label = known_labels.get((block.table_index, 0, block.column_index))
        if previous_label or (block.row_index > 0 and header_label and (block.table_index, block.row_index) not in row_has_labels):
            label = previous_label or header_label
            block.label = label
            block.mode = "variable"
            block.required = True
            block.data_type = _field_data_type(label)
            block.recognition_confidence = "high" if _field_label(label) else "medium"
            block.recognition_note = "根据左侧标签配对" if previous_label else "根据表头配对"
        elif known_labels.get(key) and block.paragraph_in_cell == 0:
            block.label = known_labels[key]
            block.mode = "fixed"
            block.required = True
            block.data_type = "text"
            block.recognition_confidence = "medium"
            block.recognition_note = "根据右侧填写值推断为标签，请核对"
        else:
            block.mode = "variable"
            block.label = block.location
            block.required = False
            block.data_type = "text"
            block.check_format = False
            block.recognition_confidence = "low"
            block.recognition_note = "无法可靠确定字段名称或对应关系，请人工确认"


def _paragraph_format(paragraph: Paragraph) -> TemplateParagraphFormat:
    run = _dominant_run(paragraph)
    font = _run_font(run, paragraph) if run is not None else FontInfo()
    pf = paragraph.paragraph_format
    spacing = _effective_paragraph_value(paragraph, "line_spacing")
    return TemplateParagraphFormat(
        font=font,
        fonts=[_run_font(r, paragraph) for r in paragraph.runs if r.text.strip()],
        alignment=_paragraph_alignment(paragraph),
        line_spacing=_line_spacing_value(spacing),
        line_spacing_kind=("atLeast" if _effective_paragraph_value(paragraph, "line_spacing_rule") == WD_LINE_SPACING.AT_LEAST else "exact") if isinstance(spacing, Length) else "multiple",
        space_before=round(pf.space_before.pt, 2) if pf.space_before is not None else None,
        space_after=round(pf.space_after.pt, 2) if pf.space_after is not None else None,
        first_line_indent_chars=_first_line_indent_chars(paragraph, font.size),
    )


def _default_mode(paragraph: Paragraph, text: str, *, first_row: bool) -> str:
    if not text.strip():
        return "ignore"
    if first_row or _heading_level(paragraph) is not None or _is_title(paragraph):
        return "fixed"
    if len(text.strip()) <= 50 and text.rstrip().endswith(("：", ":")):
        return "fixed"
    if _paragraph_alignment(paragraph) in {"center", "right"} and len(text.strip()) <= 40:
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


def _valid_data_type(value: str, data_type: str, rules: list[TemplateFieldRule] | None = None) -> bool:
    text = value.strip()
    if data_type == "text":
        return True
    if data_type == "number":
        units = {"岁", "人"} | {rule.text.strip() for rule in (rules or []) if rule.kind == "number_with_unit"}
        suffix = "|".join(re.escape(unit) for unit in sorted(units, key=len, reverse=True) if unit)
        return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:" + suffix + r")?", text))
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
    if data_type == "email":
        return bool(re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]*[A-Za-z0-9])?)+", text))
    return True


def _display_data_type(data_type: str) -> str:
    return {
        "text": "文本", "number": "数字", "date": "日期",
        "id_number": "身份证号", "phone": "电话号码", "email": "电子邮箱",
    }.get(data_type, data_type)


def draft_field_requirements(text: str) -> TemplateRequirementDraftResult:
    """只解析可确定执行的常见填写要求；不猜测无法理解的自然语言。"""
    rules: list[TemplateFieldRule] = []
    unsupported: list[str] = []
    required: bool | None = None
    for raw in re.split(r"[\n;；]+", text):
        phrase = raw.strip()
        if not phrase:
            continue
        if len(rules) >= 20:
            unsupported.append(phrase)
            continue
        compact = re.sub(r"\s+", "", phrase)
        if compact in {"必填", "必须填写", "不能为空", "不得为空", "该字段必填"}:
            required = True
            continue
        # 只从明确的用户要求生成规则；样例值本身绝不推断单位或固定答案。
        if match := re.search(r"为(.+?)时(?:不能够|不能|不得|禁止)(?:填写|填|写|使用)(.+)$", compact):
            rules.append(TemplateFieldRule(kind="forbidden_value", text=match.group(2), replacement_text=match.group(1)))
            continue
        if match := re.search(r"(?:要|应|必须)(?:填写|填|写)(?:为|成)?(.+?)(?:不能够|不能|不得)(?:填写|填|写)(.+)$", compact):
            rules.append(TemplateFieldRule(kind="exact_text", text=match.group(1)))
            continue
        if match := re.search(r"(?:必须|应|要)(?:填写|填|写)(?:为|成)?[：:]?([^，。,]+)$", compact):
            rules.append(TemplateFieldRule(kind="exact_text", text=match.group(1)))
            continue
        if match := re.search(r"(?:不能够|不能|不得|禁止)(?:填写|填|写|使用)[：:]?([^，。,]+)$", compact):
            rules.append(TemplateFieldRule(kind="forbidden_value", text=match.group(1)))
            continue
        if match := re.search(r"(?:数字后(?:必须|应|要)?(?:加|带)|(?:必须|应|要)带)([^，。,]{1,10})字?$", compact):
            unit = match.group(1).removesuffix("字")
            rules.append(TemplateFieldRule(kind="number_with_unit", text=unit))
            continue
        length = re.search(r"(\d+)\s*(?:[-~～—–至到])\s*(\d+)\s*(?:个)?(汉字|字|字符)", compact)
        number = re.search(r"(\d+(?:\.\d+)?)\s*(?:[-~～—–至到])\s*(\d+(?:\.\d+)?)\s*(?:人|岁|元|分)?", compact)
        if ("邮箱" in compact or "电子邮件" in compact) and ("格式" in compact or "有效" in compact or "符合" in compact):
            rules.append(TemplateFieldRule(kind="email"))
        elif length:
            rules.append(TemplateFieldRule(kind="chinese_length" if length.group(3) == "汉字" else "length",
                                           min_length=int(length.group(1)), max_length=int(length.group(2))))
        elif number:
            rules.append(TemplateFieldRule(kind="number_range", min_value=float(number.group(1)), max_value=float(number.group(2))))
        elif match := re.search(r"(?:只能(?:填|填写|为)|可选(?:值)?[：:]|限填)[：:]?(.+)$", compact):
            options = [part for part in re.split(r"[、，,|/]|或", match.group(1)) if part]
            if len(options) >= 2:
                rules.append(TemplateFieldRule(kind="allowed_values", options=options))
            else:
                unsupported.append(phrase)
        elif match := re.search(r"(?:必须)?包含[：:]?(.+)$", compact):
            rules.append(TemplateFieldRule(kind="contains", text=match.group(1)))
        else:
            unsupported.append(phrase)
    return TemplateRequirementDraftResult(rules=rules, unsupported=unsupported, required=required)


def _field_rule_description(rule: TemplateFieldRule, labels: dict[str, str]) -> str:
    if rule.kind == "exact_text":
        return f"必须填写「{rule.text}」"
    if rule.kind == "forbidden_value":
        return f"不得填写「{rule.text}」" + (f"；核实后建议使用「{rule.replacement_text}」" if rule.replacement_text else "")
    if rule.kind == "number_with_unit":
        return f"数字后必须带单位「{rule.text}」"
    if rule.kind == "email":
        return "有效的电子邮箱地址"
    if rule.kind in {"length", "chinese_length"}:
        unit = "汉字" if rule.kind == "chinese_length" else "字符"
        return f"{rule.min_length if rule.min_length is not None else 0}–{rule.max_length if rule.max_length is not None else '不限'} 个{unit}"
    if rule.kind == "number_range":
        return f"数值在 {rule.min_value if rule.min_value is not None else '不限'}–{rule.max_value if rule.max_value is not None else '不限'} 之间"
    if rule.kind == "allowed_values":
        return "只能填写 " + "、".join(rule.options)
    if rule.kind == "contains":
        return f"包含「{rule.text}」"
    return f"与「{labels.get(rule.other_block_id, rule.other_block_id)}」一致"


def _field_rule_matches(value: str, rule: TemplateFieldRule, target_by_id: dict[str, TemplateBlock]) -> bool:
    text = value.strip()
    if rule.kind == "exact_text":
        return text == rule.text.strip()
    if rule.kind == "forbidden_value":
        return text != rule.text.strip()
    if rule.kind == "number_with_unit":
        return bool(re.fullmatch(r"[-+]?\d+(?:\.\d+)?" + re.escape(rule.text.strip()), text))
    if rule.kind == "email":
        return _valid_data_type(text, "email")
    if rule.kind in {"length", "chinese_length"}:
        if rule.kind == "chinese_length" and not re.fullmatch(r"[\u3400-\u9fff]+", text):
            return False
        return (rule.min_length is None or len(text) >= rule.min_length) and (rule.max_length is None or len(text) <= rule.max_length)
    if rule.kind == "number_range":
        match = re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:人|岁|元)?", text)
        if not match:
            return False
        number = float(re.match(r"[-+]?\d+(?:\.\d+)?", text).group())
        return (rule.min_value is None or number >= rule.min_value) and (rule.max_value is None or number <= rule.max_value)
    if rule.kind == "allowed_values":
        return text in rule.options
    if rule.kind == "contains":
        return rule.text in text
    other = target_by_id.get(rule.other_block_id)
    return other is not None and bool(other.text.strip()) and _normal_text(text) == _normal_text(other.text)


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
        if wanted is not None:
            mismatches = [getattr(font, field) for font in (actual.fonts or [actual.font]) if not compare(getattr(font, field), wanted)]
            if mismatches:
                pairs.append(("font", field, wanted, mismatches[0]))
    paragraph_fields = (
        ("alignment", expected.alignment, actual.alignment, lambda a, e: a == e),
        ("space_before", expected.space_before, actual.space_before, lambda a, e: _num_close(a, e, 0.5)),
        ("space_after", expected.space_after, actual.space_after, lambda a, e: _num_close(a, e, 0.5)),
        ("first_line_indent_chars", expected.first_line_indent_chars, actual.first_line_indent_chars, lambda a, e: _num_close(a, e, 0.15)),
    )
    if expected.line_spacing is not None and (expected.line_spacing_kind != actual.line_spacing_kind or not _num_close(actual.line_spacing, expected.line_spacing, 0.08)):
        pairs.append(("paragraph", "line_spacing", {"kind": expected.line_spacing_kind, "value": expected.line_spacing}, {"kind": actual.line_spacing_kind, "value": actual.line_spacing}))
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
    template_labels = {block.id: block.label for block in template.blocks}
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
        elif block.mode == "variable" and value.strip() and not _valid_data_type(value, block.data_type, block.rules):
            issues.append(TemplateIssue(
                category="字段规范", severity="错误",
                message=f"{block.label or block.location}应填写为{_display_data_type(block.data_type)}",
                template_block_id=block.id, template_content_index=block.content_index,
                document_content_index=actual.content_index, expected=_display_data_type(block.data_type),
                actual=value, quote=value, repairable=True,
            ))
        if block.mode == "variable" and value.strip():
            for rule in block.rules:
                if not _field_rule_matches(value, rule, target_by_id):
                    description = _field_rule_description(rule, template_labels)
                    issues.append(TemplateIssue(
                        category="填写要求", severity="错误",
                        message=f"{block.label or block.location}不符合填写要求：{description}",
                        template_block_id=block.id, template_content_index=block.content_index,
                        document_content_index=actual.content_index,
                        expected=description, actual=value, quote=value,
                        recommended_replacement=(rule.text if rule.kind == "exact_text" else
                                                 rule.replacement_text if rule.kind == "forbidden_value" and rule.replacement_text else None),
                    ))
        if block.check_format and value.strip():
            for category, field, wanted, got in _format_differences(block.format, actual.format):
                violation = Violation(
                    scope="template", category=category, field=field, expected=wanted, actual=got,
                    message=f"{block.label or block.location}的{field}应与模板一致",
                    paragraph_index=actual.top_level_paragraph_index, paragraph_text=value,
                    severity="unknown" if got is None else "error",
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

    fixed_locations = {}
    for block in template.blocks:
        if block.mode == "fixed" and block.text.strip():
            fixed_locations.setdefault(_normal_text(block.text), set()).add(block.id)
    moved_anchor = any(_normal_text(block.text) in fixed_locations and block.id not in fixed_locations[_normal_text(block.text)] for block in target.blocks if block.text.strip())
    if template_paragraph_count != target_paragraph_count or template.table_shapes != target.table_shapes or moved_anchor:
        for issue in issues:
            issue.repairable = False
            issue.recommended_replacement = None
        issues.append(TemplateIssue(category="结构", severity="警告", message="文档区域数量或表格结构发生变化，位置映射需人工确认，本次不提供自动修订。"))
    repairable = sum(1 for issue in issues if issue.repairable)
    total = len(issues)
    return TemplateReviewResult(
        summary="表单模板审查通过" if not issues else f"共发现 {total} 项模板差异，其中 {repairable} 项可在确认后修订",
        issues=issues,
        total=total,
        repairable=repairable,
        compliant=not issues,
    )
