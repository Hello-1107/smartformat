"""docx 解析器：把 Word 文档解析为结构化、可被规则引擎比对的数据。

只做确定性解析，不调用任何 AI。产出 schema：app/schemas/document.py。
"""

from __future__ import annotations

from pathlib import Path

from docx import Document
from docx.oxml.ns import qn
from docx.shared import Length

from app.schemas.document import (
    FontInfo,
    ParsedDocument,
    ParsedParagraph,
    ParsedSection,
)

EMU_PER_CM = 360000.0

# 常见标题样式名 → 层级
_HEADING_STYLES = {
    "heading 1": 1, "heading 2": 2, "heading 3": 3,
    "heading 4": 4, "heading 5": 5, "heading 6": 6,
    "heading 7": 7, "heading 8": 8, "heading 9": 9,
    "标题 1": 1, "标题 2": 2, "标题 3": 3,
    "标题 4": 4, "标题 5": 5, "标题 6": 6,
    "标题 7": 7, "标题 8": 8, "标题 9": 9,
    "title": 1,
}

_ALIGN_XML_MAP = {
    "left": "left",
    "start": "left",
    "center": "center",
    "right": "right",
    "end": "right",
    "both": "justify",
    "distribute": "justify",
    "thaiDistribute": "justify",
    "lowKashida": "justify",
    "mediumKashida": "justify",
    "highKashida": "justify",
}


def _paragraph_alignment(paragraph: object) -> str | None:
    """直接读取 XML 并归一化对齐方式。

    新版 Word 可能写入 start/end 等逻辑方向值，旧版 python-docx 在读取
    ``paragraph_format.alignment`` 时会直接抛 ValueError，因此不能依赖枚举属性。
    """
    ppr = paragraph._p.pPr
    if ppr is None:
        return None
    jc = ppr.find(qn("w:jc"))
    if jc is None:
        return None
    raw = jc.get(qn("w:val"))
    return _ALIGN_XML_MAP.get(raw) if raw else None


def _emu_to_cm(emu: int | None) -> float | None:
    if emu is None:
        return None
    return round(emu / EMU_PER_CM, 2)


def _paper_name(width_cm: float | None, height_cm: float | None) -> str | None:
    if width_cm is None or height_cm is None:
        return None
    sizes = {
        "A4": (21.0, 29.7),
        "A3": (29.7, 42.0),
        "A5": (14.8, 21.0),
        "Letter": (21.59, 27.94),
        "Legal": (21.59, 35.56),
    }
    for name, (w, h) in sizes.items():
        if abs(width_cm - w) <= 0.25 and abs(height_cm - h) <= 0.25:
            return name
    return None


def _rfonts(run: object, kind: str) -> str | None:
    """读取 run 的 w:rFonts 指定字体（ascii / eastAsia）。"""
    rpr = run._element.rPr
    if rpr is None:
        return None
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        return None
    return rfonts.get(qn(f"w:{kind}"))


def _style_east_asia(paragraph: object) -> str | None:
    """段落样式层的中文字体兜底。"""
    style = paragraph.style
    if style is None:
        return None
    rpr = style.element.find(qn("w:rPr"))
    if rpr is None:
        return None
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        return None
    return rfonts.get(qn("w:eastAsia"))


def _heading_level(paragraph: object) -> int | None:
    """判断段落是否为标题，返回 1..6，正文返回 None。"""
    style = paragraph.style
    name = (style.name or "").strip().lower() if style is not None else ""
    if name in _HEADING_STYLES:
        level = _HEADING_STYLES[name]
        return level if level <= 6 else None
    # 兜底：w:outlineLvl（0 表示一级标题）
    ppr = paragraph._p.pPr
    if ppr is not None:
        outline = ppr.find(qn("w:outlineLvl"))
        if outline is not None:
            try:
                level = int(outline.get(qn("w:val"))) + 1
            except (TypeError, ValueError):
                level = 0
            return level if 1 <= level <= 6 else None
    return None


def _line_spacing_multiple(pf: object) -> float | None:
    """统一行距为「倍数」口径。

    python-docx 对 1.0 / 1.5 / 2.0 会返回 SINGLE / ONE_POINT_FIVE / DOUBLE 枚举，
    而不是 MULTIPLE，所以这里按「值的类型」判断而不是枚举：
    - Length → 固定值/最小值（磅），按 12pt 单倍近似换算成倍数
    - 数值   → 已经是倍数（lineRule=auto）
    """
    value = pf.line_spacing
    if value is None:
        return None
    if isinstance(value, Length):
        return round(value.pt / 12.0, 2)
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return None


def _first_line_indent_chars(paragraph: object, font_size: float | None) -> float | None:
    """优先取 w:firstLineChars，否则按字号近似换算。"""
    ppr = paragraph._p.pPr
    if ppr is not None:
        ind = ppr.find(qn("w:ind"))
        if ind is not None:
            val = ind.get(qn("w:firstLineChars"))
            if val is not None:
                try:
                    return round(int(val) / 100.0, 2)
                except ValueError:
                    pass
    pf = paragraph.paragraph_format
    if pf.first_line_indent is not None:
        base = font_size or 12.0
        return round(pf.first_line_indent.pt / base, 2)
    return None


def _list_kind(paragraph: object, numbering_el: object | None) -> tuple[bool, bool]:
    """返回 (bullet, numbered)。"""
    ppr = paragraph._p.pPr
    if ppr is None:
        return False, False
    num_pr = ppr.find(qn("w:numPr"))
    if num_pr is None:
        return False, False
    num_id_el = num_pr.find(qn("w:numId"))
    ilvl_el = num_pr.find(qn("w:ilvl"))
    num_id = num_id_el.get(qn("w:val")) if num_id_el is not None else None
    try:
        ilvl = int(ilvl_el.get(qn("w:val"))) if ilvl_el is not None else 0
    except (TypeError, ValueError):
        ilvl = 0
    if num_id is None or numbering_el is None:
        return False, True
    abstract_id: str | None = None
    for num in numbering_el.findall(qn("w:num")):
        if num.get(qn("w:numId")) == num_id:
            a = num.find(qn("w:abstractNumId"))
            abstract_id = a.get(qn("w:val")) if a is not None else None
            break
    fmt: str | None = None
    if abstract_id is not None:
        for anum in numbering_el.findall(qn("w:abstractNum")):
            if anum.get(qn("w:abstractNumId")) == abstract_id:
                for lvl in anum.findall(qn("w:lvl")):
                    try:
                        lvl_no = int(lvl.get(qn("w:ilvl")))
                    except (TypeError, ValueError):
                        continue
                    if lvl_no == ilvl:
                        nf = lvl.find(qn("w:numFmt"))
                        fmt = nf.get(qn("w:val")) if nf is not None else None
                        break
                break
    if fmt == "bullet":
        return True, False
    return False, True


def _dominant_run(paragraph: object):
    """取文本最长的 run 作为该段落的代表字体 run。"""
    runs = paragraph.runs
    if not runs:
        return None
    best = runs[0]
    best_len = len(best.text or "")
    for run in runs[1:]:
        cur_len = len(run.text or "")
        if cur_len > best_len:
            best = run
            best_len = cur_len
    return best


def _run_font(run: object, paragraph: object) -> FontInfo:
    name = _rfonts(run, "eastAsia") or _style_east_asia(paragraph)
    ascii_name = _rfonts(run, "ascii") or (
        paragraph.style.font.name if paragraph.style else None
    )
    size = run.font.size.pt if run.font.size is not None else None
    bold = run.font.bold
    italic = run.font.italic
    color: str | None = None
    if run.font.color is not None and run.font.color.rgb is not None:
        color = str(run.font.color.rgb)
    return FontInfo(
        name=name,
        ascii_name=ascii_name,
        size=size,
        bold=bold,
        italic=italic,
        color=color,
    )


def _paragraph_effective_bold_italic(paragraph: object, font: FontInfo) -> FontInfo:
    """run 未显式设置加粗/斜体时，用样式层兜底。"""
    style = paragraph.style
    if style is None:
        return font
    if font.bold is None:
        font.bold = style.font.bold
    if font.italic is None:
        font.italic = style.font.italic
    return font


def _parse_section(section: object, index: int) -> ParsedSection:
    width_cm = _emu_to_cm(section.page_width)
    height_cm = _emu_to_cm(section.page_height)
    return ParsedSection(
        index=index,
        paper=_paper_name(width_cm, height_cm),
        width_cm=width_cm,
        height_cm=height_cm,
        margin_top_cm=_emu_to_cm(section.top_margin),
        margin_bottom_cm=_emu_to_cm(section.bottom_margin),
        margin_left_cm=_emu_to_cm(section.left_margin),
        margin_right_cm=_emu_to_cm(section.right_margin),
        header_distance_cm=_emu_to_cm(section.header_distance),
        footer_distance_cm=_emu_to_cm(section.footer_distance),
    )


def parse_docx(path: str | Path) -> ParsedDocument:
    """解析 docx 为结构化数据。"""
    doc = Document(str(path))
    numbering_el = None
    try:
        numbering_part = doc.part.numbering_part
        if numbering_part is not None:
            numbering_el = numbering_part.element
    except (NotImplementedError, AttributeError):
        numbering_el = None

    sections = [_parse_section(s, i) for i, s in enumerate(doc.sections)]

    paragraphs: list[ParsedParagraph] = []
    for idx, para in enumerate(doc.paragraphs):
        text = para.text or ""
        level = _heading_level(para)
        run = _dominant_run(para)
        font = _run_font(run, para) if run is not None else FontInfo()
        font = _paragraph_effective_bold_italic(para, font)
        pf = para.paragraph_format
        bullet, numbered = _list_kind(para, numbering_el)
        paragraphs.append(
            ParsedParagraph(
                index=idx,
                text=text,
                style_name=(para.style.name if para.style is not None else ""),
                level=level,
                font=font,
                alignment=_paragraph_alignment(para),
                line_spacing=_line_spacing_multiple(pf),
                space_before=(
                    round(pf.space_before.pt, 2)
                    if pf.space_before is not None
                    else None
                ),
                space_after=(
                    round(pf.space_after.pt, 2)
                    if pf.space_after is not None
                    else None
                ),
                first_line_indent_chars=_first_line_indent_chars(para, font.size),
                numbered=numbered,
                bullet=bullet,
            )
        )

    filename = Path(path).name
    return ParsedDocument(filename=filename, sections=sections, paragraphs=paragraphs)
