"""新分析能力的定位、审查边界与工作区隔离回归。"""

from io import BytesIO

from docx import Document as WordDocument
from docx.enum.style import WD_STYLE_TYPE

from app.schemas.analysis import FieldSpec
from app.schemas.content_review import ContentIssue, ContentReviewResult
from app.schemas.document import FontInfo, ParsedDocument, ParsedParagraph
from app.schemas.rule import RuleSet
from app.services.document_analysis import check_structure, compare_fields, compare_versions
from app.services.docx_parser import parse_docx
from app.services.pdf_content import extract_pdf
from app.schemas.content_review import ContentParagraph


def _parsed(*paragraphs: tuple[str, int | None, float]) -> ParsedDocument:
    return ParsedDocument(filename="sample.docx", paragraphs=[
        ParsedParagraph(index=index, text=text, level=level, style_name="Normal", font=FontInfo(size=size))
        for index, (text, level, size) in enumerate(paragraphs)
    ])


def _word_bytes(*lines: str) -> bytes:
    document = WordDocument()
    for line in lines:
        document.add_paragraph(line)
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def test_structure_reports_missing_out_of_order_and_unmatched_figure_reference() -> None:
    parsed = _parsed(("第一章 结论", 1, 14), ("参见图 2。", None, 12), ("图 1 流程", None, 12), ("摘要", 1, 14))
    result = check_structure(4, parsed, ["摘要", "结论", "参考文献"], True)
    keys = {(item.category, item.status) for item in result.findings}
    assert ("章节", "missing") in keys
    assert ("章节", "out_of_order") in keys
    assert ("图表", "missing") in keys
    citation = next(item for item in result.findings if item.category == "图表" and item.status == "missing")
    assert citation.sources[0].paragraph_index == 1
    assert citation.sources[0].quote == "参见图 2。"


def test_structure_recognizes_plain_toc_title_and_arabic_chapter_prefix(tmp_path) -> None:
    document = WordDocument()
    document.styles.add_style("TOC 1", WD_STYLE_TYPE.PARAGRAPH)
    document.add_paragraph("目  录")
    document.add_paragraph("第2章  项目整体设计\t3", style="TOC 1")
    document.add_heading("第2章  项目整体设计", level=1)
    path = tmp_path / "with-toc.docx"
    document.save(path)

    result = check_structure(4, parse_docx(path), ["目录", "项目整体设计"], True)

    assert result.headings_found == ["目  录", "第2章  项目整体设计"]
    assert not any(item.category == "章节" for item in result.findings)


def test_structure_required_text_matches_body_without_heading_style_or_duplicate_warning() -> None:
    parsed = _parsed(
        ("正文中含有目  录文字。", None, 12),
        ("正文包含项目整体设计的说明。", None, 12),
        ("后文再次提到项目整体设计。", None, 12),
    )

    result = check_structure(4, parsed, ["目录", "项目整体设计"], True)

    assert result.headings_found == []
    assert not any(item.category == "章节" for item in result.findings)


def test_structure_required_text_order_uses_first_occurrence_even_in_body() -> None:
    parsed = _parsed(("项目整体设计先被提及。", None, 12), ("目  录", None, 12))

    result = check_structure(4, parsed, ["目录", "项目整体设计"], True)

    order_issue = next(item for item in result.findings if item.status == "out_of_order")
    assert [source.paragraph_index for source in order_issue.sources] == [1, 0]


def test_version_review_does_not_claim_removed_paragraph_issue_was_fixed() -> None:
    old = _parsed(("保留正文", None, 12), ("已删除问题段落", None, 10))
    new = _parsed(("保留正文", None, 12))
    rule = RuleSet.model_validate({"name": "字号", "body": {"font": {"size": 12}}})
    result = compare_versions(1, 2, 3, old, new, rule)
    assert result.original_issue_count >= 1
    assert result.revised_issue_count == 0
    assert any(item.category == "格式复审" and item.status == "uncertain" for item in result.findings)
    assert not any(item.category == "格式复审" and item.status == "resolved" for item in result.findings)


def test_cross_document_normalizes_units_and_keeps_ambiguous_candidates() -> None:
    contents = {
        1: [ContentParagraph(index=0, text="预算金额：1.5万元")],
        2: [ContentParagraph(index=0, text="预算金额：15000元")],
        3: [ContentParagraph(index=0, text="预算金额：15000元"), ContentParagraph(index=1, text="预算金额：16000元")],
    }
    result = compare_fields([1, 2, 3], 1, [FieldSpec(name="预算金额", value_type="number")], contents, {})
    values = result.fields[0].values
    assert [item.status for item in values] == ["baseline", "match", "ambiguous"]
    assert values[1].source.quote == "预算金额：15000元"
    assert len(values[2].candidates) == 2


def test_scanned_pdf_uses_ocr_and_preserves_page_mapping(monkeypatch) -> None:
    class Page:
        def __init__(self, text: str):
            self.text = text

        def extract_text(self, layout: bool = False) -> str:
            return self.text

    class Pdf:
        pages = [Page("第一页文字"), Page("")]

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr("app.services.pdf_content.pdfplumber.open", lambda _stream: Pdf())
    monkeypatch.setattr("app.services.pdf_content._ocr_page", lambda _content, _page: "扫描第二页")
    result = extract_pdf(b"%PDF-mocked")
    assert result["ocr_pages"] == [2]
    assert [(item["text"], item["page_number"]) for item in result["paragraphs"]] == [("第一页文字", 1), ("扫描第二页", 2)]


def test_analysis_api_rejects_cross_workspace_documents_and_pdf_format_check(client, auth, workspace, monkeypatch) -> None:
    headers, _ = auth
    other = client.post("/api/workspaces", json={"name": "第二工作区"}, headers=headers).json()["id"]
    old = client.post(f"/api/documents?workspace_id={workspace}&filename=old.docx", content=_word_bytes("预算金额：1万元"), headers=headers)
    foreign = client.post(f"/api/documents?workspace_id={other}&filename=foreign.docx", content=_word_bytes("预算金额：2万元"), headers=headers)
    assert old.status_code == foreign.status_code == 201
    wrong = client.post("/api/analysis/cross-documents", json={"workspace_id": workspace, "document_ids": [old.json()["id"], foreign.json()["id"]], "baseline_id": old.json()["id"], "fields": [{"name": "预算金额", "value_type": "number"}]}, headers=headers)
    assert wrong.status_code == 404

    monkeypatch.setattr("app.api.documents.extract_pdf", lambda _content: {"page_count": 1, "ocr_pages": [1], "paragraphs": [{"index": 0, "text": "扫描内容", "page_number": 1}]})
    pdf = client.post(f"/api/documents?workspace_id={workspace}&filename=scan.pdf", content=b"%PDF-mocked", headers=headers)
    assert pdf.status_code == 201, pdf.text
    assert pdf.json()["file_type"] == "pdf"
    assert pdf.json()["pdf_page_map"] == [1]
    assert client.get(f"/api/documents?workspace_id={workspace}", headers=headers).json()[0]["pdf_page_map"] == [1]
    rule = client.post("/api/rules/manual", json={"workspace_id": workspace, "ruleset": {"name": "字号", "body": {"font": {"size": 12}}}}, headers=headers)
    assert rule.status_code == 201, rule.text
    format_response = client.post("/api/checks", json={"workspace_id": workspace, "document_id": pdf.json()["id"], "rule_id": rule.json()["id"]}, headers=headers)
    assert format_response.status_code == 400
    monkeypatch.setattr("app.api.content_reviews.review_content", lambda paragraphs, _instructions: ContentReviewResult(summary="已审查", issues=[ContentIssue(paragraph_index=paragraphs[0].index, quote="扫描内容", category="措辞", severity="建议", reason="说明", suggestion="建议")]))
    reviewed = client.post("/api/content-reviews", json={"workspace_id": workspace, "document_id": pdf.json()["id"]}, headers=headers)
    assert reviewed.status_code == 201, reviewed.text
    assert reviewed.json()["issues"][0]["quote"] == "扫描内容"
    client.delete(f"/api/documents/{pdf.json()['id']}", headers=headers)
    assert client.get(f"/api/content-reviews?workspace_id={workspace}&document_id={pdf.json()['id']}", headers=headers).status_code == 404
