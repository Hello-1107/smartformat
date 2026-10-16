"""填写样例模板的配置、审查、版本和可控修订闭环。"""

import io

from docx import Document
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn


def _set_logical_end_alignment(paragraph) -> None:
    """模拟新版 Word 产生、旧版 python-docx 枚举不认识的合法对齐值。"""
    ppr = paragraph._p.get_or_add_pPr()
    jc = ppr.find(qn("w:jc"))
    if jc is None:
        jc = OxmlElement("w:jc")
        ppr.append(jc)
    jc.set(qn("w:val"), "end")


def _template_bytes(title: str = "申请表") -> bytes:
    doc = Document()
    heading = doc.add_paragraph(title)
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("张三")
    doc.add_paragraph("33")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "关系"
    table.cell(0, 1).text = "姓名"
    table.cell(1, 0).text = "兄长"
    table.cell(1, 1).text = "张三"
    _set_logical_end_alignment(table.cell(1, 1).paragraphs[0])
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _target_bytes() -> bytes:
    doc = Document()
    heading = doc.add_paragraph("报名表")
    heading.alignment = WD_ALIGN_PARAGRAPH.CENTER
    doc.add_paragraph("李四")
    doc.add_paragraph("三十三")
    table = doc.add_table(rows=2, cols=2)
    table.cell(0, 0).text = "关系"
    table.cell(0, 1).text = "姓名"
    table.cell(1, 0).text = "兄长"
    table.cell(1, 1).text = "李四"
    _set_logical_end_alignment(table.cell(1, 1).paragraphs[0])
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def _upload_template(client, headers, workspace, content: bytes, name="申请模板"):
    response = client.post(
        "/api/template-audits/template",
        params={"workspace_id": workspace, "filename": "template.docx", "name": name},
        content=content,
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_template_review_distinguishes_fixed_and_variable_and_repairs(client, auth, workspace) -> None:
    headers, _ = auth
    template = _upload_template(client, headers, workspace, _template_bytes())
    blocks = template["config"]["blocks"]
    for block in blocks:
        if block["id"] == "p:0":
            block.update(label="表单标题", mode="fixed", required=True, data_type="text", check_format=True)
        elif block["id"] == "p:1":
            block.update(label="申请人姓名", mode="variable", required=True, data_type="text", check_format=False)
        elif block["id"] == "p:2":
            block.update(label="年龄", mode="variable", required=True, data_type="number", check_format=False)
        elif block["row_index"] == 1:
            block.update(mode="variable", required=True, data_type="text", check_format=False)
    update = client.put(
        "/api/template-audits/current",
        json={
            "workspace_id": workspace,
            "name": "申请模板",
            "check_page": True,
            "blocks": [{key: block[key] for key in ("id", "label", "mode", "required", "data_type", "check_format")} for block in blocks],
        },
        headers=headers,
    )
    assert update.status_code == 200, update.text

    uploaded = client.post(
        "/api/documents",
        params={"workspace_id": workspace, "filename": "target.docx"},
        content=_target_bytes(),
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    assert uploaded.status_code == 201, uploaded.text
    document_id = uploaded.json()["id"]
    reviewed = client.post(
        "/api/template-audits/reviews",
        json={"workspace_id": workspace, "document_id": document_id},
        headers=headers,
    )
    assert reviewed.status_code == 201, reviewed.text
    result = reviewed.json()
    assert any(issue["category"] == "固定内容" and issue["recommended_replacement"] == "申请表" for issue in result["issues"])
    assert any(issue["category"] == "字段规范" and issue["actual"] == "三十三" for issue in result["issues"])
    assert not any(issue.get("actual") == "李四" and issue["category"] == "固定内容" for issue in result["issues"])

    fixed_index = next(index for index, issue in enumerate(result["issues"]) if issue["category"] == "固定内容")
    age_index = next(index for index, issue in enumerate(result["issues"]) if issue["category"] == "字段规范")
    revised = client.post(
        f"/api/documents/{document_id}/revised-copy",
        json={
            "workspace_id": workspace,
            "format_violation_indexes": [],
            "content_fixes": [],
            "template_fixes": [
                {"review_id": result["id"], "issue_index": fixed_index, "replacement_text": "申请表"},
                {"review_id": result["id"], "issue_index": age_index, "replacement_text": "33"},
            ],
        },
        headers=headers,
    )
    assert revised.status_code == 200, revised.text
    revised_doc = Document(io.BytesIO(revised.content))
    assert revised_doc.paragraphs[0].text == "申请表"
    assert revised_doc.paragraphs[1].text == "李四"
    assert revised_doc.paragraphs[2].text == "33"
    assert "修订清单" in [paragraph.text for paragraph in revised_doc.paragraphs]


def test_template_versions_can_be_reactivated(client, auth, workspace) -> None:
    headers, _ = auth
    first = _upload_template(client, headers, workspace, _template_bytes("模板一"), "模板一")
    second = _upload_template(client, headers, workspace, _template_bytes("模板二"), "模板二")
    assert first["version"] == 1
    assert second["version"] == 2
    versions = client.get(
        "/api/template-audits/versions", params={"workspace_id": workspace}, headers=headers
    ).json()
    assert [item["version"] for item in versions] == [2, 1]
    restored = client.post(
        f"/api/template-audits/versions/{first['id']}/activate",
        params={"workspace_id": workspace}, headers=headers,
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["version"] == 1
    current = client.get(
        "/api/template-audits/current", params={"workspace_id": workspace}, headers=headers
    )
    assert current.json()["id"] == first["id"]


def test_unpublished_template_cannot_review(client, auth, workspace) -> None:
    headers, _ = auth
    template = _upload_template(client, headers, workspace, _template_bytes())
    assert template["is_published"] is False
    uploaded = client.post(
        "/api/documents",
        params={"workspace_id": workspace, "filename": "target.docx"},
        content=_target_bytes(),
        headers={**headers, "Content-Type": "application/octet-stream"},
    )
    response = client.post(
        "/api/template-audits/reviews",
        json={"workspace_id": workspace, "document_id": uploaded.json()["id"]},
        headers=headers,
    )
    assert response.status_code == 400
    assert "保存发布" in response.json()["detail"]
