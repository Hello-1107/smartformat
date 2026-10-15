"""内容审查的引用校验、鉴权、持久化与预览定位回归测试（不联网）。"""

import io
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import parse_xml
from docx.text.paragraph import Paragraph

from app.schemas.content_review import ContentParagraph
from app.services import deepseek_content
from app.services.document_content import read_content, preview_bytes, validate_content


def sample_bytes() -> bytes:
    doc = Document()
    doc.sections[0].header.paragraphs[0].text = "页眉不参加审查"
    doc.add_paragraph("本季度销售额为100万元。")
    doc.add_paragraph("")
    doc.add_table(rows=1, cols=1).cell(0, 0).text = "本季度销售额为200万元。"
    doc.add_paragraph("本季度销售额为100万元。")
    doc.add_paragraph("分页前").add_run().add_break()
    stream = io.BytesIO()
    doc.save(stream)
    return stream.getvalue()


def fake_response(monkeypatch, result=None, finish_reason="stop"):
    if result is None:
        result = {
            "summary": "销售额存在矛盾",
            "issues": [{
                "paragraph_index": 2, "quote": "本季度销售额为200万元。",
                "category": "一致性", "severity": "重要",
                "reason": "与前文100万元不一致", "suggestion": "核对财务数据，统一销售额。",
                "recommended_replacement": "本季度销售额数据待核实。",
            }],
        }
    calls = []

    class FakeClient:
        def __init__(self, **kwargs):
            self.chat = SimpleNamespace(completions=self)

        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def create(self, **kwargs):
            calls.append(kwargs)
            content = result if isinstance(result, str) else json.dumps(result, ensure_ascii=False)
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason=finish_reason, message=SimpleNamespace(content=content)
            )])

    monkeypatch.setattr(deepseek_content, "OpenAI", FakeClient)
    return calls


def upload(client, headers, workspace):
    response = client.post(
        "/api/documents", params={"workspace_id": workspace, "filename": "content.docx"},
        content=sample_bytes(), headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_content_and_preview_share_anchors(tmp_path):
    path = tmp_path / "sample.docx"
    path.write_bytes(sample_bytes())
    original = path.read_bytes()
    paragraphs = read_content(path)
    assert [p.index for p in paragraphs] == [0, 2, 3, 4]
    assert "200万元" in paragraphs[1].text
    with ZipFile(io.BytesIO(preview_bytes(path))) as archive:
        root = parse_xml(archive.read("word/document.xml"))
        for paragraph in paragraphs:
            anchor = root.xpath(f'//w:bookmarkStart[@w:name="sf_content_{paragraph.index}"]')
            assert len(anchor) == 1
            assert Paragraph(anchor[0].getparent(), None).text == paragraph.text
        formats = root.xpath('./w:body/w:p')
        for index, element in enumerate(formats):
            assert element.xpath(f'./w:bookmarkStart[@w:name="sf_format_{index}"]')
        assert not root.xpath('//w:tbl//w:bookmarkStart[starts-with(@w:name, "sf_format_")]')
    assert path.read_bytes() == original


def test_content_review_roundtrip(client, auth, workspace, monkeypatch):
    headers, _ = auth
    document_id = upload(client, headers, workspace)
    calls = fake_response(monkeypatch)
    response = client.post("/api/content-reviews", json={
        "workspace_id": workspace, "document_id": document_id, "instructions": "检查数据一致性",
    }, headers=headers)
    assert response.status_code == 201, response.text
    item = response.json()
    assert item["paragraph_count"] == 4
    assert item["issues"][0]["paragraph_index"] == 2
    assert item["issues"][0]["recommended_replacement"] == "本季度销售额数据待核实。"
    prompt = json.loads(calls[0]["messages"][1]["content"])
    assert prompt["review_focus"] == "检查数据一致性"
    assert prompt["paragraphs"][1]["text"] == "本季度销售额为200万元。"
    history = client.get("/api/content-reviews", params={
        "workspace_id": workspace, "document_id": document_id,
    }, headers=headers)
    assert history.json()[0]["id"] == item["id"]
    assert client.delete(f"/api/content-reviews/{item['id']}", headers=headers).status_code == 204
    assert client.get("/api/content-reviews", params={
        "workspace_id": workspace, "document_id": document_id,
    }, headers=headers).json() == []
    # 重新创建一条，继续覆盖预览与删除文档后的级联行为。
    response = client.post("/api/content-reviews", json={
        "workspace_id": workspace, "document_id": document_id, "instructions": "检查数据一致性",
    }, headers=headers)
    assert response.status_code == 201, response.text
    preview = client.get(f"/api/documents/{document_id}/preview", headers=headers)
    assert preview.status_code == 200
    assert b"sf_content_2" in ZipFile(io.BytesIO(preview.content)).read("word/document.xml")
    download = client.get(f"/api/documents/{document_id}/download", headers=headers)
    assert b"sf_content_2" not in ZipFile(io.BytesIO(download.content)).read("word/document.xml")
    client.delete(f"/api/documents/{document_id}", headers=headers)
    assert client.get("/api/content-reviews", params={
        "workspace_id": workspace, "document_id": document_id,
    }, headers=headers).status_code == 404


@pytest.mark.parametrize("change", ["quote", "index", "json", "truncated"])
def test_reject_unlocatable_or_invalid_model_output(monkeypatch, change):
    result = {"summary": "发现问题", "issues": [{
        "paragraph_index": 0, "quote": "原文", "category": "措辞", "severity": "建议",
        "reason": "表述不清", "suggestion": "补充描述",
    }]}
    if change == "quote":
        result["issues"][0]["quote"] = "编造的原文"
    if change == "index":
        result["issues"][0]["paragraph_index"] = 99
    fake_response(monkeypatch, "not-json" if change == "json" else result,
                  finish_reason="length" if change == "truncated" else "stop")
    with pytest.raises(ValueError):
        deepseek_content.review_content([ContentParagraph(index=0, text="原文")])


def test_content_limits_and_empty_results(monkeypatch):
    with pytest.raises(ValueError):
        validate_content([])
    with pytest.raises(ValueError):
        validate_content([ContentParagraph(index=0, text="字" * 30001)])
    fake_response(monkeypatch, {"summary": "本次未发现明显问题", "issues": []})
    assert deepseek_content.review_content([ContentParagraph(index=0, text="原文")]).issues == []


def test_review_access_and_failure_do_not_save(client, auth, workspace, monkeypatch):
    headers, _ = auth
    document_id = upload(client, headers, workspace)
    other = client.post("/api/auth/register", json={
        "username": "other", "password": "secret123", "confirm_password": "secret123",
    }).json()
    foreign = {"Authorization": "Bearer " + other["access_token"]}
    body = {"workspace_id": workspace, "document_id": document_id}
    assert client.post("/api/content-reviews", json=body, headers=foreign).status_code == 403
    assert client.get("/api/content-reviews", params=body, headers=foreign).status_code == 403
    assert client.get(f"/api/documents/{document_id}/preview", headers=foreign).status_code == 403
    other_workspace = client.post("/api/workspaces", json={"name": "另一个"}, headers=headers).json()["id"]
    assert client.post("/api/content-reviews", json={
        **body, "workspace_id": other_workspace,
    }, headers=headers).status_code == 404
    fake_response(monkeypatch, "invalid")
    response = client.post("/api/content-reviews", json=body, headers=headers)
    assert response.status_code == 502
    assert client.get("/api/content-reviews", params=body, headers=headers).json() == []
    monkeypatch.setattr(deepseek_content.settings, "deepseek_api_key", "")
    assert client.post("/api/content-reviews", json=body, headers=headers).status_code == 503
