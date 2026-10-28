"""当前审查结果导出的定位、建议与工作区隔离回归。"""

from io import BytesIO

from docx import Document as WordDocument
from docx.shared import Pt

from app.schemas.content_review import ContentIssue, ContentReviewResult
from app.services.document_content import content_locations


def _word_bytes(first_text: str = "普通正文需要核对") -> bytes:
    document = WordDocument()
    paragraph = document.add_paragraph()
    run = paragraph.add_run(first_text)
    run.font.size = Pt(10)
    document.add_table(rows=1, cols=1).cell(0, 0).text = "表格原文需要修改"
    output = BytesIO()
    document.save(output)
    return output.getvalue()


def _text(content: bytes) -> str:
    document = WordDocument(BytesIO(content))
    return "\n".join(paragraph.text for paragraph in document.paragraphs)


def _upload(client, workspace: int, headers: dict[str, str], name: str = "测试材料.docx",
            content: bytes | None = None) -> int:
    response = client.post(f"/api/documents?workspace_id={workspace}&filename={name}", content=content or _word_bytes(), headers=headers)
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_content_locations_include_table_row_and_column(tmp_path) -> None:
    path = tmp_path / "source.docx"
    path.write_bytes(_word_bytes())
    positions = content_locations(path)
    assert positions[0] == "正文第 1 段"
    assert positions[1] == "第 1 个表格第 1 行第 1 列，单元格第 1 段"


def test_format_report_exports_selected_record_with_quote_and_suggestion(client, auth, workspace) -> None:
    headers, _ = auth
    document_id = _upload(client, workspace, headers)
    rule = client.post("/api/rules/manual", json={"workspace_id": workspace, "ruleset": {"name": "字号规则", "body": {"font": {"size": 16}}}}, headers=headers)
    assert rule.status_code == 201, rule.text
    checked = client.post("/api/checks", json={"workspace_id": workspace, "document_id": document_id, "rule_id": rule.json()["id"]}, headers=headers)
    assert checked.status_code == 201, checked.text
    exported = client.get(f"/api/reports/checks/{checked.json()['id']}", headers=headers)
    assert exported.status_code == 200, exported.text
    assert exported.headers["content-type"].startswith("application/vnd.openxmlformats-officedocument.wordprocessingml.document")
    body = _text(exported.content)
    assert "测试材料.docx" in body
    assert "正文第 1 段" in body
    assert "普通正文需要核对" in body
    assert "修改建议" in body
    assert "16" in body


def test_content_report_uses_table_location_and_stored_ai_advice(client, auth, workspace, monkeypatch) -> None:
    headers, _ = auth
    document_id = _upload(client, workspace, headers)

    def fake_review(paragraphs, _instructions):
        target = next(item for item in paragraphs if "表格原文" in item.text)
        return ContentReviewResult(summary="表格建议", issues=[ContentIssue(
            paragraph_index=target.index, quote="表格原文", category="措辞", severity="建议",
            reason="表达不够清楚", suggestion="请人工核对后调整措辞",
        )])

    monkeypatch.setattr("app.api.content_reviews.review_content", fake_review)
    reviewed = client.post("/api/content-reviews", json={"workspace_id": workspace, "document_id": document_id}, headers=headers)
    assert reviewed.status_code == 201, reviewed.text
    exported = client.get(f"/api/reports/content-reviews/{reviewed.json()['id']}", headers=headers)
    assert exported.status_code == 200, exported.text
    body = _text(exported.content)
    assert "第 1 个表格第 1 行第 1 列" in body
    assert "表格原文" in body
    assert "请人工核对后调整措辞" in body


def test_pdf_content_report_preserves_page_number(client, auth, workspace, monkeypatch) -> None:
    headers, _ = auth
    monkeypatch.setattr("app.api.documents.extract_pdf", lambda _bytes: {
        "page_count": 3, "ocr_pages": [3],
        "paragraphs": [{"index": 0, "text": "第三页待核对", "page_number": 3}],
    })
    uploaded = client.post(f"/api/documents?workspace_id={workspace}&filename=scan.pdf", content=b"%PDF-mocked", headers=headers)
    assert uploaded.status_code == 201, uploaded.text
    monkeypatch.setattr("app.api.content_reviews.review_content", lambda paragraphs, _instructions: ContentReviewResult(
        summary="扫描件建议", issues=[ContentIssue(paragraph_index=0, quote="第三页待核对", category="措辞",
                                      severity="建议", reason="需核实", suggestion="对照原页修改")]))
    reviewed = client.post("/api/content-reviews", json={"workspace_id": workspace, "document_id": uploaded.json()["id"]}, headers=headers)
    assert reviewed.status_code == 201, reviewed.text
    exported = client.get(f"/api/reports/content-reviews/{reviewed.json()['id']}", headers=headers)
    assert exported.status_code == 200, exported.text
    assert "第 3 页" in _text(exported.content)
    assert "OCR" in _text(exported.content)


def test_analysis_export_requires_untampered_current_result_and_existing_document(client, auth, workspace) -> None:
    headers, _ = auth
    document_id = _upload(client, workspace, headers)
    analyzed = client.post("/api/analysis/structure", json={"workspace_id": workspace, "document_id": document_id,
                                                      "required_headings": ["摘要"], "require_order": True}, headers=headers)
    assert analyzed.status_code == 200, analyzed.text
    result = analyzed.json()
    assert result["export_signature"]
    route = "/api/reports/analysis/structure"
    exported = client.post(route, json={"workspace_id": workspace, "result": result}, headers=headers)
    assert exported.status_code == 200, exported.text
    assert "测试材料.docx" in _text(exported.content)
    assert "缺少必需章节" in _text(exported.content)
    changed = {**result, "findings": [{**result["findings"][0], "message": "伪造结论"}]}
    assert client.post(route, json={"workspace_id": workspace, "result": changed}, headers=headers).status_code == 400
    assert client.delete(f"/api/documents/{document_id}", headers=headers).status_code == 204
    assert client.post(route, json={"workspace_id": workspace, "result": result}, headers=headers).status_code == 404


def test_report_access_checks_workspace_membership(client, auth, workspace) -> None:
    headers, _ = auth
    document_id = _upload(client, workspace, headers)
    rule = client.post("/api/rules/manual", json={"workspace_id": workspace, "ruleset": {"name": "字号", "body": {"font": {"size": 16}}}}, headers=headers).json()
    check = client.post("/api/checks", json={"workspace_id": workspace, "document_id": document_id, "rule_id": rule["id"]}, headers=headers).json()
    another = client.post("/api/auth/register", json={"username": "anotheruser", "password": "secret123", "confirm_password": "secret123"})
    assert another.status_code == 201, another.text
    other_headers = {"Authorization": f"Bearer {another.json()['access_token']}"}
    assert client.get(f"/api/reports/checks/{check['id']}", headers=other_headers).status_code == 403


def test_template_report_uses_selected_review_and_template_snapshot(client, auth, workspace) -> None:
    headers, _ = auth
    template = client.post("/api/template-audits/template",
                           params={"workspace_id": workspace, "filename": "template.docx", "name": "标准表单"},
                           content=_word_bytes("标准标题"), headers=headers)
    assert template.status_code == 201, template.text
    blocks = template.json()["config"]["blocks"]
    first = next(block for block in blocks if block["kind"] == "paragraph")
    configured = client.put("/api/template-audits/current", json={
        "workspace_id": workspace, "name": "标准表单", "check_page": False,
        "blocks": [{"id": block["id"], "label": "固定标题" if block["id"] == first["id"] else "内容",
                    "mode": "fixed" if block["id"] == first["id"] else "ignore", "required": True,
                    "data_type": "text", "check_format": False} for block in blocks],
    }, headers=headers)
    assert configured.status_code == 200, configured.text
    document_id = _upload(client, workspace, headers, "表单待审.docx", _word_bytes("错误标题"))
    reviewed = client.post("/api/template-audits/reviews", json={"workspace_id": workspace, "document_id": document_id}, headers=headers)
    assert reviewed.status_code == 201, reviewed.text
    exported = client.get(f"/api/reports/template-reviews/{reviewed.json()['id']}", headers=headers)
    assert exported.status_code == 200, exported.text
    body = _text(exported.content)
    assert "表单待审.docx" in body
    assert "正文第 1 段" in body
    assert "错误标题" in body
    assert "标准标题" in body
    assert "模板版本" in body


def test_cross_document_report_names_both_sources_and_baseline(client, auth, workspace) -> None:
    headers, _ = auth
    baseline_id = _upload(client, workspace, headers, "基准.docx", _word_bytes("预算金额：100元"))
    changed_id = _upload(client, workspace, headers, "待核对.docx", _word_bytes("预算金额：200元"))
    analyzed = client.post("/api/analysis/cross-documents", json={
        "workspace_id": workspace, "document_ids": [baseline_id, changed_id], "baseline_id": baseline_id,
        "fields": [{"name": "预算金额", "value_type": "number", "aliases": []}],
    }, headers=headers)
    assert analyzed.status_code == 200, analyzed.text
    exported = client.post("/api/reports/analysis/cross-documents", json={"workspace_id": workspace, "result": analyzed.json()}, headers=headers)
    assert exported.status_code == 200, exported.text
    body = _text(exported.content)
    assert "基准.docx" in body
    assert "待核对.docx" in body
    assert "预算金额：100元" in body
    assert "预算金额：200元" in body
    assert "正文第 1 段" in body
