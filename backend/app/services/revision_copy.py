"""确定性生成 Word 修订后副本。

本模块不调用 DeepSeek。格式修改仅采用违规项中已经确定的期望值；内容修改仅采用
用户在界面确认并提交的替换文本。源文件始终只读，输出只存在于内存响应中。
"""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH, WD_LINE_SPACING
from docx.text.run import Run
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import qn
from docx.shared import Cm, Pt, RGBColor
from docx.text.paragraph import Paragraph
from lxml import etree

from app.schemas.check import Violation
from app.services.document_content import _paragraphs


class RepairError(ValueError):
    """所选修订项不能安全、确定性地应用。"""


@dataclass(frozen=True)
class ContentReplacement:
    paragraph_index: int
    quote: str
    replacement_text: str
    category: str


@dataclass(frozen=True)
class RevisionEntry:
    kind: str
    location: str
    before: str
    after: str


_ALIGNMENT = {
    "left": WD_ALIGN_PARAGRAPH.LEFT,
    "center": WD_ALIGN_PARAGRAPH.CENTER,
    "right": WD_ALIGN_PARAGRAPH.RIGHT,
    "justify": WD_ALIGN_PARAGRAPH.JUSTIFY,
}
_PAGE_SIZES_CM = {
    "a3": (29.7, 42.0),
    "a4": (21.0, 29.7),
    "a5": (14.8, 21.0),
    "letter": (21.59, 27.94),
    "legal": (21.59, 35.56),
}
_REPAIRABLE_FORMAT_FIELDS = {
    ("font", "name"),
    ("font", "ascii_name"),
    ("font", "size"),
    ("font", "bold"),
    ("font", "italic"),
    ("font", "color"),
    ("paragraph", "alignment"),
    ("paragraph", "line_spacing"),
    ("paragraph", "space_before"),
    ("paragraph", "space_after"),
    ("paragraph", "first_line_indent_chars"),
    ("page", "paper"),
    ("page", "width_cm"),
    ("page", "height_cm"),
    ("page", "margin_top_cm"),
    ("page", "margin_bottom_cm"),
    ("page", "margin_left_cm"),
    ("page", "margin_right_cm"),
    ("page", "header_distance_cm"),
    ("page", "footer_distance_cm"),
}


def is_repairable_format(violation: Violation) -> bool:
    """供路由和测试复用的确定性修订能力白名单。"""
    return violation.severity != "unknown" and (violation.category, violation.field) in _REPAIRABLE_FORMAT_FIELDS


def _display(value: object) -> str:
    if value is None:
        return "未设置"
    if isinstance(value, bool):
        return "是" if value else "否"
    return str(value)


def _runs(paragraph: Paragraph):
    if not paragraph.runs:
        raise RepairError("目标段落没有可设置格式的文字，无法安全修订")
    return paragraph.runs


def _rfonts(run: object):
    rpr = run._element.get_or_add_rPr()
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        rfonts = OxmlElement("w:rFonts")
        rpr.append(rfonts)
    return rfonts


def _set_font(paragraph: Paragraph, field: str, expected: object, run_index: int | None = None) -> None:
    runs = [r for e in paragraph._p.xpath("./w:r | ./w:hyperlink/w:r") if (r := Run(e, paragraph)).text.strip()]
    if run_index is not None:
        if not 0 <= run_index < len(runs):
            raise RepairError("文字片段已变化，请重新审查")
        runs = [runs[run_index]]
    for run in runs or _runs(paragraph):
        if field == "name":
            value = str(expected)
            # 只覆写中文字体，不能借由 font.name 连带覆盖 ASCII 字体。
            _rfonts(run).set(qn("w:eastAsia"), value)
        elif field == "ascii_name":
            value = str(expected)
            run.font.name = value
            fonts = _rfonts(run)
            fonts.set(qn("w:ascii"), value)
            fonts.set(qn("w:hAnsi"), value)
        elif field == "size":
            run.font.size = Pt(float(expected))
        elif field == "bold":
            run.font.bold = bool(expected)
        elif field == "italic":
            run.font.italic = bool(expected)
        elif field == "color":
            color = str(expected).lstrip("#")
            if len(color) != 6 or any(char not in "0123456789abcdefABCDEF" for char in color):
                raise RepairError("字体颜色不是有效的六位十六进制值")
            run.font.color.rgb = RGBColor.from_string(color)
        else:
            raise RepairError(f"暂不支持自动修复字体字段「{field}」")


def _set_first_line_indent(paragraph: Paragraph, chars: float) -> None:
    """同时写入 Word 的字符缩进，保持与解析器的读取口径一致。"""
    paragraph.paragraph_format.first_line_indent = Pt(12 * chars)
    ppr = paragraph._p.get_or_add_pPr()
    indent = ppr.find(qn("w:ind"))
    if indent is None:
        indent = OxmlElement("w:ind")
        ppr.append(indent)
    indent.set(qn("w:firstLineChars"), str(round(chars * 100)))


def _set_paragraph(paragraph: Paragraph, field: str, expected: object) -> None:
    fmt = paragraph.paragraph_format
    if field == "alignment":
        value = _ALIGNMENT.get(str(expected))
        if value is None:
            raise RepairError("未知的段落对齐方式")
        fmt.alignment = value
    elif field == "line_spacing":
        if isinstance(expected, dict):
            kind, value = expected["kind"], float(expected["value"])
            fmt.line_spacing = value if kind == "multiple" else Pt(value)
            fmt.line_spacing_rule = {"multiple": WD_LINE_SPACING.MULTIPLE, "exact": WD_LINE_SPACING.EXACTLY, "atLeast": WD_LINE_SPACING.AT_LEAST}[kind]
        else:
            fmt.line_spacing = float(expected)
    elif field == "space_before":
        fmt.space_before = Pt(float(expected))
    elif field == "space_after":
        fmt.space_after = Pt(float(expected))
    elif field == "first_line_indent_chars":
        _set_first_line_indent(paragraph, float(expected))
    else:
        raise RepairError(f"暂不支持自动修复段落字段「{field}」")


def _set_page(doc: Document, field: str, expected: object, section_index: int | None = None) -> None:
    if section_index is None and len(doc.sections) > 1:
        raise RepairError("旧报告缺少页面节定位，请重新审查后修订")
    index = section_index if section_index is not None else 0
    if not 0 <= index < len(doc.sections):
        raise RepairError("页面节已变化，请重新审查")
    for section in [doc.sections[index]]:
        if field == "paper":
            size = _PAGE_SIZES_CM.get(str(expected).lower())
            if size is None:
                raise RepairError(f"暂不支持自动设置纸张「{expected}」")
            section.page_width, section.page_height = Cm(size[0]), Cm(size[1])
        elif field == "width_cm":
            section.page_width = Cm(float(expected))
        elif field == "height_cm":
            section.page_height = Cm(float(expected))
        elif field == "margin_top_cm":
            section.top_margin = Cm(float(expected))
        elif field == "margin_bottom_cm":
            section.bottom_margin = Cm(float(expected))
        elif field == "margin_left_cm":
            section.left_margin = Cm(float(expected))
        elif field == "margin_right_cm":
            section.right_margin = Cm(float(expected))
        elif field == "header_distance_cm":
            section.header_distance = Cm(float(expected))
        elif field == "footer_distance_cm":
            section.footer_distance = Cm(float(expected))
        else:
            raise RepairError(f"暂不支持自动修复页面字段「{field}」")


def _apply_format_fixes(doc: Document, violations: list[Violation]) -> list[RevisionEntry]:
    entries: list[RevisionEntry] = []
    for violation in violations:
        if not is_repairable_format(violation):
            raise RepairError(f"「{violation.message}」暂不支持自动修复")
        if violation.category == "page":
            _set_page(doc, violation.field, violation.expected, violation.section_index)
            location = f"页面节 {(violation.section_index or 0) + 1}"
        else:
            index = violation.paragraph_index
            if index is None or not 0 <= index < len(doc.paragraphs):
                raise RepairError("格式问题缺少可定位的正文段落，无法安全修订")
            paragraph = doc.paragraphs[index]
            if violation.category == "font":
                _set_font(paragraph, violation.field, violation.expected, violation.run_index)
            elif violation.category == "paragraph":
                _set_paragraph(paragraph, violation.field, violation.expected)
            else:
                raise RepairError(f"「{violation.message}」暂不支持自动修复")
            location = f"正文段落 {index + 1}"
        entries.append(
            RevisionEntry(
                kind="格式修订",
                location=location,
                before=f"{violation.field}: {_display(violation.actual)}",
                after=f"{violation.field}: {_display(violation.expected)}",
            )
        )
    return entries


def _text_nodes(element: etree._Element) -> list[etree._Element]:
    return list(element.xpath(".//w:t"))


def _node_text(nodes: list[etree._Element]) -> str:
    return "".join(node.text or "" for node in nodes)


def _set_text(node: etree._Element, value: str) -> None:
    node.text = value
    space = "{http://www.w3.org/XML/1998/namespace}space"
    if value[:1].isspace() or value[-1:].isspace():
        node.set(space, "preserve")
    else:
        node.attrib.pop(space, None)


def _replace_once(element: etree._Element, quote: str, replacement: str) -> None:
    nodes = _text_nodes(element)
    original = _node_text(nodes)
    if original.count(quote) != 1:
        raise RepairError("内容引用在段落中不唯一或包含非文本元素，无法安全替换")
    start = original.index(quote)
    end = start + len(quote)
    cursor = 0
    start_node = end_node = -1
    start_offset = end_offset = 0
    for node_index, node in enumerate(nodes):
        length = len(node.text or "")
        if start_node < 0 and start <= cursor + length:
            start_node, start_offset = node_index, start - cursor
        if end <= cursor + length:
            end_node, end_offset = node_index, end - cursor
            break
        cursor += length
    if start_node < 0 or end_node < 0:
        raise RepairError("无法确定内容引用的文本边界")
    if start_node == end_node:
        text = nodes[start_node].text or ""
        _set_text(nodes[start_node], text[:start_offset] + replacement + text[end_offset:])
        return
    first = nodes[start_node].text or ""
    last = nodes[end_node].text or ""
    _set_text(nodes[start_node], first[:start_offset] + replacement)
    for node in nodes[start_node + 1:end_node]:
        _set_text(node, "")
    _set_text(nodes[end_node], last[end_offset:])


def _apply_content_fixes(data: bytes, fixes: list[ContentReplacement]) -> tuple[bytes, list[RevisionEntry]]:
    if not fixes:
        return data, []
    grouped: dict[int, list[ContentReplacement]] = {}
    for fix in fixes:
        grouped.setdefault(fix.paragraph_index, []).append(fix)

    output = BytesIO()
    entries: list[RevisionEntry] = []
    with ZipFile(BytesIO(data)) as source:
        root = parse_xml(source.read("word/document.xml"))
        paragraphs = _paragraphs(root)
        for index, replacements in grouped.items():
            if not 0 <= index < len(paragraphs):
                raise RepairError("内容建议定位的段落已不存在，无法生成副本")
            element = paragraphs[index]
            original = Paragraph(element, None).text
            positions: list[tuple[int, int, ContentReplacement]] = []
            for fix in replacements:
                if original.count(fix.quote) != 1:
                    raise RepairError("内容建议引用与原文不唯一或已变化，请重新审查后再生成副本")
                start = original.index(fix.quote)
                positions.append((start, start + len(fix.quote), fix))
            positions.sort(key=lambda item: item[0], reverse=True)
            last_start = len(original) + 1
            for start, end, fix in positions:
                if end > last_start:
                    raise RepairError("已选择的内容建议引用发生重叠，不能同时自动修订")
                _replace_once(element, fix.quote, fix.replacement_text)
                entries.append(
                    RevisionEntry(
                        kind="内容修订",
                        location=f"内容段落 {index + 1}（{fix.category}）",
                        before=fix.quote,
                        after=fix.replacement_text,
                    )
                )
                last_start = start
        with ZipFile(output, "w") as target:
            for item in source.infolist():
                xml = etree.tostring(root) if item.filename == "word/document.xml" else source.read(item.filename)
                target.writestr(item, xml)
    return output.getvalue(), entries


def _append_revision_list(data: bytes, source_name: str, entries: list[RevisionEntry]) -> bytes:
    doc = Document(BytesIO(data))
    doc.add_page_break()
    # 不能依赖用户文档包含内置 Heading 1 样式，否则自定义模板会导出失败。
    heading = doc.add_paragraph()
    heading_run = heading.add_run("修订清单")
    heading_run.bold = True
    heading_run.font.size = Pt(16)
    doc.add_paragraph(
        f"本副本由已确认的 {len(entries)} 项修订生成；原始文件「{source_name}」未被修改。"
    )
    table = doc.add_table(rows=1, cols=4)
    # 部分用户模板会移除内置表格样式；修订清单仍应能导出。
    try:
        table.style = "Table Grid"
    except KeyError:
        pass
    for cell, title in zip(table.rows[0].cells, ("类型", "位置", "修订前", "修订后"), strict=True):
        cell.text = title
    for entry in entries:
        cells = table.add_row().cells
        for cell, value in zip(cells, (entry.kind, entry.location, entry.before, entry.after), strict=True):
            cell.text = value
    result = BytesIO()
    doc.save(result)
    return result.getvalue()


def build_revised_copy(
    source_path: str | Path,
    source_name: str,
    format_violations: list[Violation],
    content_fixes: list[ContentReplacement],
) -> bytes:
    """生成内存中的修订副本并附加修订清单，绝不写入或替换源文件。"""
    if not format_violations and not content_fixes:
        raise RepairError("请至少选择一项要修订的问题")
    seen = {}
    previous = []
    for violation in format_violations:
        key = (violation.category, violation.field, violation.section_index, violation.paragraph_index, violation.run_index)
        if key in seen and seen[key] != violation.expected:
            raise RepairError("选中的格式修订存在冲突，请仅保留同一位置的一组期望值")
        if violation.category == "font":
            for other in previous:
                if (other.category == "font" and other.field == violation.field
                    and other.paragraph_index == violation.paragraph_index
                    and (other.run_index is None or violation.run_index is None or other.run_index == violation.run_index)
                    and other.expected != violation.expected):
                    raise RepairError("整段格式与局部文字的修订要求发生冲突，请选择其中一项")
        seen[key] = violation.expected
        previous.append(violation)
    doc = Document(str(source_path))
    entries = _apply_format_fixes(doc, format_violations)
    formatted = BytesIO()
    doc.save(formatted)
    revised, content_entries = _apply_content_fixes(formatted.getvalue(), content_fixes)
    return _append_revision_list(revised, source_name, [*entries, *content_entries])
