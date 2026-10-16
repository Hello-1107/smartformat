"""正文/表格文本与预览锚点共享同一 XML 遍历顺序。"""

from io import BytesIO
from pathlib import Path
from zipfile import ZipFile

from docx.oxml.ns import qn
from docx.oxml import parse_xml
from docx.text.paragraph import Paragraph
from lxml import etree

from app.schemas.content_review import ContentParagraph

MAX_CONTENT_CHARS = 30000
MAX_CONTENT_PARAGRAPHS = 1500


def _paragraphs(root: etree._Element) -> list[etree._Element]:
    # 含表格及内容控件，不含文本框及已删除的修订内容。
    return root.xpath(
        "./w:body//w:p[not(ancestor::w:txbxContent) and not(ancestor::w:del)]"
    )


def read_content(path: str | Path) -> list[ContentParagraph]:
    with ZipFile(path) as archive:
        root = parse_xml(archive.read("word/document.xml"))
    paragraphs = []
    for index, element in enumerate(_paragraphs(root)):
        text = Paragraph(element, None).text
        if text.strip():
            paragraphs.append(ContentParagraph(index=index, text=text))
    return paragraphs


def validate_content(paragraphs: list[ContentParagraph]) -> None:
    if not paragraphs:
        raise ValueError("文档没有可审查的正文或表格文字")
    if len(paragraphs) > MAX_CONTENT_PARAGRAPHS or sum(
        len(p.text) for p in paragraphs
    ) > MAX_CONTENT_CHARS:
        raise ValueError("单次内容审查支持最多 30000 字符、1500 个非空段落，请拆分文档后审查")


def preview_bytes(path: str | Path, content_prefix: str = "sf_content") -> bytes:
    """仅在内存中的预览副本插入书签，原始下载文件不变。"""
    output = BytesIO()
    with ZipFile(path) as source:
        root = parse_xml(source.read("word/document.xml"))
        ids = [int(value) for value in root.xpath("//w:bookmarkStart/@w:id") if value.isdigit()]
        next_id = max(ids, default=0) + 1

        def add_anchor(element: etree._Element, name: str) -> None:
            nonlocal next_id
            start = etree.Element(qn("w:bookmarkStart"))
            start.set(qn("w:id"), str(next_id))
            start.set(qn("w:name"), name)
            end = etree.Element(qn("w:bookmarkEnd"))
            end.set(qn("w:id"), str(next_id))
            next_id += 1
            # pPr 必须保持为首个子元素。
            offset = 1 if len(element) and element[0].tag == qn("w:pPr") else 0
            element.insert(offset, start)
            element.insert(offset + 1, end)

        for index, element in enumerate(root.xpath("./w:body/w:p")):
            add_anchor(element, f"sf_format_{index}")
        for index, element in enumerate(_paragraphs(root)):
            add_anchor(element, f"{content_prefix}_{index}")
        with ZipFile(output, "w") as target:
            for item in source.infolist():
                data = etree.tostring(root) if item.filename == "word/document.xml" else source.read(item.filename)
                target.writestr(item, data)
    return output.getvalue()
