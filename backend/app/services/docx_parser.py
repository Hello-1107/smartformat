"""docx 解析器：把 Word 文档解析为结构化、可被规则引擎比对的数据。

只做确定性解析，不调用任何 AI。产出 schema：app/schemas/document.py。
"""

from __future__ import annotations

from pathlib import Path
from copy import deepcopy
from typing import Iterator, Any
import re
from lxml import etree

from docx import Document
from docx.oxml.ns import qn
from docx.oxml import OxmlElement
from docx.text.paragraph import Paragraph
from docx.shared import Length
from docx.text.run import Run
from docx.enum.text import WD_LINE_SPACING

from app.schemas.document import (
    FontInfo,
    ParsedDocument,
    ParsedParagraph,
    ParsedSection,
    ParsedRun,
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


def _alignment_from_ppr(ppr: object | None) -> str | None:
    if ppr is None:
        return None
    jc = ppr.find(qn("w:jc"))
    if jc is None:
        return None
    raw = jc.get(qn("w:val"))
    return _ALIGN_XML_MAP.get(raw) if raw else None


def _style_chain(style: object | None) -> Iterator[Any]:
    """按当前样式到基样式的顺序迭代，并防止异常文档形成循环。"""
    seen: set[str] = set()
    while style is not None:
        key = getattr(style, "style_id", None) or str(id(style))
        if key in seen:
            break
        seen.add(key)
        yield style
        style = getattr(style, "base_style", None)


def _paragraph_alignment(paragraph: object) -> str | None:
    """读取直接格式或段落样式中的对齐方式并归一化。

    新版 Word 可能写入 start/end 等逻辑方向值，旧版 python-docx 在读取
    ``paragraph_format.alignment`` 时会直接抛 ValueError，因此不能依赖枚举属性。
    """
    direct = _alignment_from_ppr(paragraph._p.pPr)
    if direct is not None:
        return direct
    for style in _style_chain(paragraph.style):
        value = _alignment_from_ppr(style.element.find(qn("w:pPr")))
        if value is not None:
            return value
    return _alignment_from_ppr(_default_ppr(paragraph)) or "left"


def _default_ppr(paragraph: Any) -> etree._Element | None:
    values = paragraph.part.styles.element.xpath("./w:docDefaults/w:pPrDefault/w:pPr")
    return values[0] if values else None


def _default_run(paragraph: Any) -> Run:
    element = OxmlElement("w:r")
    values = paragraph.part.styles.element.xpath("./w:docDefaults/w:rPrDefault/w:rPr")
    if values:
        element.append(deepcopy(values[0]))
    return Run(element, paragraph)


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


def _style_rfont(style: object, kind: str) -> str | None:
    rpr = style.element.find(qn("w:rPr"))
    if rpr is None:
        return None
    rfonts = rpr.find(qn("w:rFonts"))
    if rfonts is None:
        return None
    return rfonts.get(qn(f"w:{kind}"))


def _font_styles(run: object, paragraph: object) -> Iterator[Any]:
    seen: set[str] = set()
    for root in (getattr(run, "style", None), paragraph.style):
        for style in _style_chain(root):
            key = getattr(style, "style_id", None) or str(id(style))
            if key in seen:
                continue
            seen.add(key)
            yield style


def _style_font_value(styles: list[object], field: str) -> Any:
    for style in styles:
        value = getattr(style.font, field)
        if value is not None:
            return value
    return None


def _heading_level(paragraph: object) -> int | None:
    """判断段落是否为标题，返回 1..6，正文返回 None。"""
    sources = [(paragraph._p.pPr, "")]
    sources.extend((s.element.find(qn("w:pPr")), (s.name or "").strip().lower()) for s in _style_chain(paragraph.style))
    for ppr, name in sources:
        if ppr is not None:
            outline = ppr.find(qn("w:outlineLvl"))
            if outline is not None:
                try:
                    level = int(outline.get(qn("w:val"))) + 1
                except (TypeError, ValueError):
                    return None
                return level if 1 <= level <= 6 else None
        if name in _HEADING_STYLES:
            level = _HEADING_STYLES[name]
            return level if level <= 6 else None
    return None


def _is_title(paragraph: object) -> bool:
    return any((s.name or "").strip().lower() in {"title", "标题"} for s in _style_chain(paragraph.style))


_TOC_STYLE = re.compile(r"^(?:toc|目录)\s*([1-9])$", re.I)
_CAPTION = re.compile(r"^\s*([图表])\s*[0-9一二三四五六七八九十]+(?:[-—.．][0-9]+)*")
_CODE_TOKEN = re.compile(
    r"(?:[{};]|=>|==|!=|</?[A-Za-z]|@\w+|\b(?:class|interface|public|private|protected|"
    r"function|const|let|var|import|export|return|SELECT|INSERT|UPDATE|DELETE)\b)", re.I,
)
_CODE_PREFIX = re.compile(
    r"^(?:[/#*]|@\w+|</?[A-Za-z]|(?:async\s+)?(?:function|class|interface|public|private|"
    r"protected|static|const|let|var|import|export|return|throw|if|else|for|while|try|catch|"
    r"switch|case|new|SELECT|INSERT|UPDATE|DELETE)\b)", re.I,
)


def _toc_level(style_name: str) -> int | None:
    match = _TOC_STYLE.match(style_name.strip())
    return int(match.group(1)) if match else None


def _paragraph_role(text: str, style_name: str, level: int | None, is_title: bool) -> tuple[str, int | None]:
    """确定性标记段落用途，供模板审查避免把代码和题注当作正文。"""
    if is_title:
        return "title", None
    if level is not None:
        return "heading", None
    toc_level = _toc_level(style_name)
    if toc_level is not None:
        return "toc", toc_level
    caption = _CAPTION.match(text)
    if caption:
        return ("figure_caption" if caption.group(1) == "图" else "table_caption"), None
    style_key = style_name.strip().casefold()
    if any(token in style_key for token in ("code", "代码", "preformatted", "源程序")):
        return "code", None
    stripped = text.strip()
    compact = re.sub(r"\s+", "", stripped)
    ascii_count = len(re.findall(r"[A-Za-z0-9_{}();=<>/@\[\]]", compact))
    ascii_ratio = ascii_count / len(compact) if compact else 0.0
    code_tokens = len(_CODE_TOKEN.findall(stripped))
    structural_line = bool(re.fullmatch(r"[{}\[\](),;]+", compact))
    code_ending = stripped.endswith((";", "{", "}"))
    if (
        structural_line
        or (_CODE_PREFIX.match(stripped) and ascii_ratio >= 0.4)
        or (code_ending and code_tokens >= 1 and ascii_ratio >= 0.45)
        or (code_tokens >= 2 and ascii_ratio >= 0.55)
    ):
        return "code", None
    return "body", None


def _line_spacing_value(value: object | None) -> float | None:
    """读取行距数值，固定/最小行距保留磅数，由类型字段区分。

    python-docx 对 1.0 / 1.5 / 2.0 会返回 SINGLE / ONE_POINT_FIVE / DOUBLE 枚举，
    而不是 MULTIPLE，所以这里按「值的类型」判断而不是枚举：
    - Length → 固定值/最小值（磅）
    - 数值   → 已经是倍数（lineRule=auto）
    """
    if value is None:
        return None
    if isinstance(value, Length):
        return round(value.pt, 2)
    if isinstance(value, (int, float)):
        return round(float(value), 2)
    return None


def _line_spacing_multiple(pf: object) -> float | None:
    """兼容其他服务按 python-docx paragraph_format 调用。"""
    return _line_spacing_value(pf.line_spacing)


def _effective_paragraph_value(paragraph: object, field: str) -> Any:
    value = getattr(paragraph.paragraph_format, field)
    if value is not None:
        return value
    for style in _style_chain(paragraph.style):
        value = getattr(style.paragraph_format, field)
        if value is not None:
            return value
    default = _default_ppr(paragraph)
    if default is not None:
        element = OxmlElement("w:p")
        element.append(deepcopy(default))
        return getattr(Paragraph(element, None).paragraph_format, field)
    return None


def _first_line_indent_chars(paragraph: object, font_size: float | None) -> float | None:
    """优先取直接或样式的 w:firstLineChars，否则按字号近似换算。"""
    pprs = [paragraph._p.pPr]
    pprs.extend(style.element.find(qn("w:pPr")) for style in _style_chain(paragraph.style))
    for ppr in pprs:
        if ppr is None:
            continue
        ind = ppr.find(qn("w:ind"))
        if ind is not None:
            val = ind.get(qn("w:firstLineChars"))
            if val is not None:
                try:
                    return round(int(val) / 100.0, 2)
                except ValueError:
                    pass
            if ind.get(qn("w:firstLine")) is not None or ind.get(qn("w:hanging")) is not None:
                break
    first_line_indent = _effective_paragraph_value(paragraph, "first_line_indent")
    if first_line_indent is not None:
        if font_size is None:
            return None
        base = font_size
        return round(first_line_indent.pt / base, 2)
    return 0.0


def _list_kind(paragraph: object, numbering_el: object | None) -> tuple[bool, bool]:
    """返回 (bullet, numbered)。"""
    pprs = [paragraph._p.pPr, *[s.element.find(qn("w:pPr")) for s in _style_chain(paragraph.style)]]
    num_id_el = ilvl_el = None
    for ppr in pprs:
        num_pr = ppr.find(qn("w:numPr")) if ppr is not None else None
        if num_pr is not None:
            if num_id_el is None:
                num_id_el = num_pr.find(qn("w:numId"))
            if ilvl_el is None:
                ilvl_el = num_pr.find(qn("w:ilvl"))
    if num_id_el is None:
        return False, False
    num_id = num_id_el.get(qn("w:val")) if num_id_el is not None else None
    if num_id == "0":
        return False, False
    try:
        ilvl = int(ilvl_el.get(qn("w:val"))) if ilvl_el is not None else 0
    except (TypeError, ValueError):
        ilvl = 0
    if num_id is None or numbering_el is None:
        return False, True
    abstract_id: str | None = None
    override_fmt = None
    for num in numbering_el.findall(qn("w:num")):
        if num.get(qn("w:numId")) == num_id:
            a = num.find(qn("w:abstractNumId"))
            abstract_id = a.get(qn("w:val")) if a is not None else None
            for override in num.findall(qn("w:lvlOverride")):
                if override.get(qn("w:ilvl")) == str(ilvl):
                    fmt_el = override.find("./" + qn("w:lvl") + "/" + qn("w:numFmt"))
                    override_fmt = fmt_el.get(qn("w:val")) if fmt_el is not None else None
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
    fmt = override_fmt or fmt
    if fmt == "bullet":
        return True, False
    return False, True


def _dominant_run(paragraph: Any) -> Run | None:
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
    styles = list(_font_styles(run, paragraph))
    name = _rfonts(run, "eastAsia")
    if name is None:
        name = next(
            (value for style in styles if (value := _style_rfont(style, "eastAsia")) is not None),
            None,
        )
    ascii_name = _rfonts(run, "ascii") or _rfonts(run, "hAnsi") or run.font.name
    if ascii_name is None:
        ascii_name = next(
            (
                value
                for style in styles
                if (value := _style_rfont(style, "ascii") or _style_rfont(style, "hAnsi"))
                is not None
            ),
            None,
        ) or _style_font_value(styles, "name")
    defaults = _default_run(paragraph)
    name = name or _rfonts(defaults, "eastAsia")
    ascii_name = ascii_name or _rfonts(defaults, "ascii") or _rfonts(defaults, "hAnsi")
    size_value = run.font.size or _style_font_value(styles, "size") or defaults.font.size
    size = size_value.pt if size_value is not None else None
    bold = run.font.bold
    if bold is None:
        bold = _style_font_value(styles, "bold")
    italic = run.font.italic
    if italic is None:
        italic = _style_font_value(styles, "italic")
    color: str | None = None
    if run.font.color is not None and run.font.color.rgb is not None:
        color = str(run.font.color.rgb)
    if color is None:
        for style in styles:
            if style.font.color is not None and style.font.color.rgb is not None:
                color = str(style.font.color.rgb)
                break
    return FontInfo(
        name=name,
        ascii_name=ascii_name,
        size=size,
        bold=bold,
        italic=italic,
        color=color,
    )


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
        is_title = _is_title(para)
        style_name = para.style.name if para.style is not None else ""
        role, toc_level = _paragraph_role(text, style_name, level, is_title)
        run = _dominant_run(para)
        font = _run_font(run, para) if run is not None else FontInfo()
        runs = [ParsedRun(text=r.text, font=_run_font(r, para)) for e in para._p.xpath("./w:r | ./w:hyperlink/w:r") if (r := Run(e, para)).text.strip()]
        line_spacing = _effective_paragraph_value(para, "line_spacing")
        space_before = _effective_paragraph_value(para, "space_before")
        space_after = _effective_paragraph_value(para, "space_after")
        bullet, numbered = _list_kind(para, numbering_el)
        paragraphs.append(
            ParsedParagraph(
                index=idx,
                text=text,
                style_name=style_name,
                level=level,
                is_title=is_title,
                runs=runs,
                font=font,
                alignment=_paragraph_alignment(para),
                line_spacing=_line_spacing_value(line_spacing),
                line_spacing_kind=("atLeast" if _effective_paragraph_value(para, "line_spacing_rule") == WD_LINE_SPACING.AT_LEAST else "exact") if isinstance(line_spacing, Length) else "multiple",
                space_before=(
                    round(space_before.pt, 2)
                    if space_before is not None
                    else None
                ),
                space_after=(
                    round(space_after.pt, 2)
                    if space_after is not None
                    else None
                ),
                first_line_indent_chars=_first_line_indent_chars(para, font.size),
                numbered=numbered,
                bullet=bullet,
                role=role,
                toc_level=toc_level,
            )
        )

    filename = Path(path).name
    return ParsedDocument(filename=filename, sections=sections, paragraphs=paragraphs)
