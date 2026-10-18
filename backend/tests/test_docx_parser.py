"""docx 解析器测试：用 python-docx 生成样本再解析验证。"""

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml.ns import qn
from docx.shared import Cm, Pt

from app.services.docx_parser import parse_docx


def _make_docx(path) -> None:
    doc = Document()
    section = doc.sections[0]
    section.page_width = Cm(21.0)
    section.page_height = Cm(29.7)
    section.top_margin = Cm(2.54)
    section.left_margin = Cm(3.17)

    # 标题
    h = doc.add_heading("1 引言", level=1)
    h_run = h.runs[0]
    h_run.font.size = Pt(16)
    h_run.font.bold = True
    h_run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "黑体")

    # 正文
    p = doc.add_paragraph("这是正文内容")
    run = p.runs[0]
    run.font.name = "Times New Roman"
    run.font.size = Pt(12)
    run._element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
    pf = p.paragraph_format
    pf.alignment = WD_ALIGN_PARAGRAPH.JUSTIFY
    pf.line_spacing = 1.5

    doc.save(path)


def test_parse_docx(tmp_path) -> None:
    path = tmp_path / "sample.docx"
    _make_docx(path)
    parsed = parse_docx(path)

    assert parsed.sections[0].paper == "A4"
    assert parsed.sections[0].margin_left_cm == 3.17

    headings = [p for p in parsed.paragraphs if p.level is not None]
    bodies = [p for p in parsed.paragraphs if p.level is None]
    assert len(headings) == 1
    assert headings[0].font.bold is True
    assert headings[0].font.size == 16

    assert len(bodies) >= 1
    body = bodies[0]
    assert body.alignment == "justify"
    assert body.line_spacing == 1.5
    assert body.font.name == "宋体"
    assert body.font.ascii_name == "Times New Roman"
    assert body.font.size == 12


def test_parse_docx_resolves_paragraph_style_formatting(tmp_path) -> None:
    doc = Document()
    heading_style = doc.styles["Heading 2"]
    heading_style.font.size = Pt(15)
    heading_style.font.bold = True
    heading_style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "黑体")
    heading_style.paragraph_format.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_heading("二级标题", level=2)

    body_style = doc.styles["Normal"]
    body_style.font.size = Pt(11)
    body_style.element.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), "宋体")
    body_style.paragraph_format.line_spacing = 1.25
    doc.add_paragraph("样式正文")

    path = tmp_path / "style-based.docx"
    doc.save(path)
    parsed = parse_docx(path)

    heading = next(item for item in parsed.paragraphs if item.level == 2)
    body = next(item for item in parsed.paragraphs if item.text == "样式正文")
    assert heading.font.name == "黑体"
    assert heading.font.size == 15
    assert heading.font.bold is True
    assert heading.alignment == "center"
    assert body.font.name == "宋体"
    assert body.font.size == 11
    assert body.line_spacing == 1.25
