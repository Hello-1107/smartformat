"""表单 AI 建议仅处理显式选中字段，且不接受无法定位的引用。"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.api import template_audits
from app.schemas.template_audit import (TemplateAiReview, TemplateAiSuggestion, TemplateBlock,
                                        TemplateConfiguration, TemplateReviewCreate, TemplateReviewResult)
from app.services import deepseek_template_content
from app.services.report_export import ReportDocument, template_report


def _block(block_id: str, label: str) -> TemplateBlock:
    return TemplateBlock(id=block_id, order=0, kind="table_cell", location="表格 1 第 1 行",
                         content_index=0, label=label, mode="variable", requirement_text="填写时避免简称")


def _fake_client(monkeypatch, result):
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
                finish_reason="stop", message=SimpleNamespace(content=json.dumps(result, ensure_ascii=False)),
            )])

    monkeypatch.setattr(deepseek_template_content, "OpenAI", FakeClient)
    return calls


def test_ai_reviews_only_selected_field_and_validates_quote(monkeypatch):
    monkeypatch.setattr(deepseek_template_content.settings, "deepseek_api_key", "test-key")
    calls = _fake_client(monkeypatch, {"summary": "有一条建议", "suggestions": [{
        "block_id": "politics", "quote": "团员", "reason": "简称可能不符合要求",
        "suggestion": "核对真实政治面貌后使用完整名称", "recommended_replacement": None,
    }]})
    result = deepseek_template_content.review_template_fields(
        [(_block("politics", "政治面貌"), "团员")], {"politics": "政治面貌", "secret": "其他字段"},
    )
    assert result.status == "completed"
    assert result.suggestions[0].quote == "团员"
    payload = json.loads(calls[0]["messages"][1]["content"])
    assert len(payload["fields"]) == 1
    assert payload["fields"][0]["value"] == "团员"
    assert "secret" not in calls[0]["messages"][1]["content"]


def test_ai_rejects_hallucinated_quote_after_one_retry(monkeypatch, caplog):
    monkeypatch.setattr(deepseek_template_content.settings, "deepseek_api_key", "test-key")
    calls = _fake_client(monkeypatch, {"summary": "有一条建议", "suggestions": [{
        "block_id": "politics", "quote": "编造的原文", "reason": "原因", "suggestion": "建议",
    }]})
    with pytest.raises(ValueError):
        deepseek_template_content.review_template_fields(
            [(_block("politics", "政治面貌"), "团员")], {"politics": "政治面貌"},
        )
    assert len(calls) == 2
    assert "团员" not in caplog.text


def test_ai_does_not_call_model_when_not_configured(monkeypatch):
    monkeypatch.setattr(deepseek_template_content.settings, "deepseek_api_key", "")
    result = deepseek_template_content.review_template_fields(
        [(_block("politics", "政治面貌"), "团员")], {"politics": "政治面貌"},
    )
    assert result.status == "not_configured"


def test_ai_suggestion_is_separate_from_compliance_and_exported():
    result = TemplateReviewResult(
        summary="表单模板审查通过", issues=[], total=0, repairable=0, compliant=True,
        ai_review=TemplateAiReview(status="completed", summary="有一条人工核实建议", model="test-model",
            field_ids=["politics"], suggestions=[TemplateAiSuggestion(
                block_id="politics", document_content_index=0, quote="团员",
                reason="简称可能有歧义", suggestion="核实政治面貌后填写完整名称",
            )]),
    )
    review = SimpleNamespace(result_json={**result.model_dump(), "template_snapshot": {
        "config": {"blocks": [{"id": "politics", "label": "政治面貌", "location": "表格 1"}]},
    }}, template_version=2, created_at=None, id=1)
    report = template_report(review, ReportDocument(id=1, filename="form.docx", file_type="docx",
                                                    content_positions={0: "表格 1 第 1 行"}))
    assert result.compliant is True
    assert len(report.issues) == 1
    assert report.issues[0].category == "AI填写建议"
    assert "模板版本：2" in report.basis


def test_ai_failure_keeps_deterministic_review_and_requirement_snapshot(monkeypatch, tmp_path):
    path = tmp_path / "form.docx"
    path.write_bytes(b"test-placeholder")
    block = _block("people", "家庭人口数")
    block.requirement_text = "人数要写6人不能写6"
    config = TemplateConfiguration(blocks=[block])
    template = SimpleNamespace(id=3, workspace_id=1, version=2, name="表单", filename="template.docx",
        stored_path=str(path), size=100, is_active=True, is_published=True, is_review_active=True,
        config_json=config.model_dump(), created_at=datetime.now(timezone.utc))
    document = SimpleNamespace(id=4, workspace_id=1, file_type="docx", stored_path=str(path))

    class FakeDb:
        def get(self, model, item_id):
            return document

        def add(self, item):
            self.review = item

        def commit(self):
            pass

        def refresh(self, item):
            item.id = 8
            item.created_at = datetime.now(timezone.utc)

    monkeypatch.setattr(template_audits, "require_membership", lambda *_: None)
    monkeypatch.setattr(template_audits, "_active", lambda *_: template)
    monkeypatch.setattr(template_audits, "review_against_template", lambda *_: TemplateReviewResult(
        summary="表单模板审查通过", issues=[], total=0, repairable=0, compliant=True))
    monkeypatch.setattr(template_audits, "extract_template_configuration", lambda *_: config)

    def fail_ai(*_):
        raise ValueError("invalid model output")

    monkeypatch.setattr(template_audits, "review_template_fields", fail_ai)
    result = template_audits.create_template_review(
        TemplateReviewCreate(workspace_id=1, document_id=4, ai_field_ids=["people"]),
        db=FakeDb(), user=SimpleNamespace(id=9),
    )
    assert result.compliant is True
    assert result.ai_review.status == "failed"
    assert result.template_snapshot["config"]["blocks"][0]["requirement_text"] == "人数要写6人不能写6"
