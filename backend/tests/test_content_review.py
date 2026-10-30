"""内容审查的引用校验、鉴权、持久化与预览定位回归测试（不联网）。"""

import io
import json
from types import SimpleNamespace
from zipfile import ZipFile

import pytest
from docx import Document
from docx.oxml import parse_xml
from docx.text.paragraph import Paragraph

from app.schemas.content_review import ContentIssue, ContentParagraph, ContentReviewResult
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


def test_content_review_normalizes_known_model_variants(monkeypatch):
    fake_response(monkeypatch, {"summary": "发现一处问题", "issues": [{
        "paragraph_index": "0", "quote": "原文", "category": "逻辑问题", "severity": "中等",
        "reason": "表述有歧义", "suggestion": "明确含义",
        "related_references": [{"paragraph_index": "1", "quote": "依据"}],
    }]})
    result = deepseek_content.review_content([
        ContentParagraph(index=0, text="原文"), ContentParagraph(index=1, text="依据"),
    ])
    assert result.issues[0].paragraph_index == 0
    assert result.issues[0].category == "逻辑"
    assert result.issues[0].severity == "一般"
    assert result.issues[0].related_references[0].paragraph_index == 1
    assert '"category":"措辞|语法' not in deepseek_content.SYSTEM_PROMPT


def test_content_review_repairs_invalid_structure_once(monkeypatch, caplog):
    monkeypatch.setattr(deepseek_content.settings, "deepseek_api_key", "test-key")
    responses = [
        {"summary": "发现问题", "issues": [{"paragraph_index": 0, "quote": "私密原文",
            "category": "未知分类", "severity": "建议", "reason": "不清晰", "suggestion": "修改"}]},
        {"summary": "发现问题", "issues": [{"paragraph_index": 0, "quote": "私密原文",
            "category": "措辞", "severity": "建议", "reason": "不清晰", "suggestion": "修改"}]},
    ]
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
            return SimpleNamespace(choices=[SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=json.dumps(responses.pop(0), ensure_ascii=False)),
            )])

    monkeypatch.setattr(deepseek_content, "OpenAI", FakeClient)
    result = deepseek_content.review_content([ContentParagraph(index=0, text="私密原文")])
    assert len(result.issues) == 1
    assert len(calls) == 2
    assert len(calls[1]["messages"]) == 4
    assert "issues.0.category" in calls[1]["messages"][-1]["content"]
    assert "私密原文" not in caplog.text


def test_safe_chunking_uses_small_requests_and_keeps_source_indexes(monkeypatch):
    paragraphs = [ContentParagraph(index=index * 2, text=f"第{index}段需要审查。" * 10) for index in range(450)]
    assert deepseek_content.needs_safe_chunking(paragraphs)
    calls = []

    def fake_review(part, _instructions=""):
        calls.append(part)
        first = part[0]
        return ContentReviewResult(summary="已审查", issues=[ContentIssue(
            paragraph_index=first.index, quote=first.text[:3], category="措辞", severity="建议",
            reason="测试原因", suggestion="测试建议",
        )])

    monkeypatch.setattr(deepseek_content, "review_content", fake_review)
    result = deepseek_content.review_content_chunked(paragraphs, cross_review=False)
    assert len(calls) >= 3
    assert all(len(part) <= 200 and sum(len(p.text) for p in part) <= 8000 for part in calls)
    assert {issue.paragraph_index for issue in result.issues} == {part[0].index for part in calls}
    assert "未执行额外的跨段" in result.summary


def test_failed_optional_cross_review_is_disclosed_without_losing_checked_segments(monkeypatch):
    paragraphs = [ContentParagraph(index=index, text=f"原文第{index}段。") for index in range(210)]

    def fake_review(part, instructions=""):
        if "重点复核" in instructions:
            raise ValueError("模型引用无效")
        first = part[0]
        return ContentReviewResult(summary="已审查", issues=[ContentIssue(
            paragraph_index=first.index, quote=first.text, category="措辞", severity="建议",
            reason="测试原因", suggestion="测试建议",
        )])

    monkeypatch.setattr(deepseek_content, "review_content", fake_review)
    result = deepseek_content.review_content_chunked(paragraphs)
    assert {issue.paragraph_index for issue in result.issues} == {0, 200}
    assert "跨段一致性复核未完成" in result.summary


def test_invalid_large_chunk_retries_smaller_groups_without_accepting_bad_quotes(monkeypatch):
    paragraphs = [ContentParagraph(index=index, text=f"原文第{index}段。") for index in range(4)]
    calls = []

    def fake_review(part, _instructions=""):
        calls.append([p.index for p in part])
        if len(part) > 2:
            raise ValueError("原文引用无效")
        return ContentReviewResult(summary="已审查", issues=[])

    monkeypatch.setattr(deepseek_content, "review_content", fake_review)
    result = deepseek_content.review_content_chunked(paragraphs, cross_review=False)
    assert calls == [[0, 1, 2, 3], [0, 1], [2, 3]]
    assert "已完成 2 个分段" in result.summary


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
