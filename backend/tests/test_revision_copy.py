"""修订后副本必须只读原件、确定性应用已确认项目并附修订清单。"""

import io

from docx import Document
from docx.shared import Pt

from app.schemas.content_review import ContentIssue, ContentReviewResult
from app.schemas.rule import FontRule, RuleSet, ScopeRule


def _source_bytes() -> bytes:
    doc = Document()
    paragraph = doc.add_paragraph()
    run = paragraph.add_run("原句错误。")
    run.font.size = Pt(14)
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def test_generate_revised_copy_keeps_original_and_appends_manifest(
    client, auth, workspace, monkeypatch
) -> None:
    headers, _ = auth
    upload = client.post(
        "/api/documents",
        params={"workspace_id": workspace, "filename": "原文.docx"},
        content=_source_bytes(),
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert upload.status_code == 201, upload.text
    document_id = upload.json()["id"]

    ruleset = RuleSet(name="字号规则", body=ScopeRule(font=FontRule(size=12)))
    monkeypatch.setattr("app.api.rules.extract_ruleset", lambda _text: ruleset)
    rule = client.post(
        "/api/rules",
        json={"workspace_id": workspace, "natural_language": "正文为 12pt"},
        headers=headers,
    )
    assert rule.status_code == 201, rule.text
    check = client.post(
        "/api/checks",
        json={
            "workspace_id": workspace,
            "document_id": document_id,
            "rule_id": rule.json()["id"],
        },
        headers=headers,
    )
    assert check.status_code == 201, check.text
    size_index = next(
        index for index, violation in enumerate(check.json()["violations"])
        if violation["category"] == "font" and violation["field"] == "size"
    )

    reviewed = ContentReviewResult(
        summary="存在可修订的句子",
        issues=[ContentIssue(
            paragraph_index=0,
            quote="原句错误。",
            category="措辞",
            severity="建议",
            reason="表达不够准确",
            suggestion="原句已修正。",
        )],
    )
    monkeypatch.setattr("app.api.content_reviews.review_content", lambda *_args: reviewed)
    content_review = client.post(
        "/api/content-reviews",
        json={"workspace_id": workspace, "document_id": document_id},
        headers=headers,
    )
    assert content_review.status_code == 201, content_review.text

    original = client.get(f"/api/documents/{document_id}/download", headers=headers)
    revised = client.post(
        f"/api/documents/{document_id}/revised-copy",
        json={
            "workspace_id": workspace,
            "check_id": check.json()["id"],
            "format_violation_indexes": [size_index],
            "content_fixes": [{
                "review_id": content_review.json()["id"],
                "issue_index": 0,
                "replacement_text": "原句已修正。",
            }],
        },
        headers=headers,
    )
    assert revised.status_code == 200, revised.text
    assert "attachment" in revised.headers["content-disposition"]

    original_doc = Document(io.BytesIO(original.content))
    assert original_doc.paragraphs[0].text == "原句错误。"
    assert "修订清单" not in [paragraph.text for paragraph in original_doc.paragraphs]

    revised_doc = Document(io.BytesIO(revised.content))
    assert revised_doc.paragraphs[0].text == "原句已修正。"
    assert revised_doc.paragraphs[0].runs[0].font.size.pt == 12
    assert "修订清单" in [paragraph.text for paragraph in revised_doc.paragraphs]
    assert any("原句错误。" in cell.text for table in revised_doc.tables for row in table.rows for cell in row.cells)


def test_revised_copy_rejects_empty_selection(client, auth, workspace) -> None:
    headers, _ = auth
    upload = client.post(
        "/api/documents",
        params={"workspace_id": workspace, "filename": "empty.docx"},
        content=_source_bytes(),
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    document_id = upload.json()["id"]
    response = client.post(
        f"/api/documents/{document_id}/revised-copy",
        json={"workspace_id": workspace, "format_violation_indexes": [], "content_fixes": []},
        headers=headers,
    )
    assert response.status_code == 400
    assert "至少选择" in response.json()["detail"]
