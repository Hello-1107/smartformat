"""自然语言格式规则提取：常见中文表达与无效响应重试。"""

import json
from types import SimpleNamespace

import pytest

from app.services import deepseek_spec


TEXT = "题目：黑体、三号字、居中。\n正文：宋体，小四，首行缩进2字，行间距：固定值22，段后间距自动。"


def _response(data):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=data))])


def _client(monkeypatch, responses):
    calls = []

    class Client:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        @property
        def chat(self):
            return SimpleNamespace(completions=SimpleNamespace(create=self.create))

        def create(self, **kwargs):
            calls.append(kwargs)
            return responses.pop(0)

    monkeypatch.setattr(deepseek_spec.settings, "deepseek_api_key", "test-key")
    monkeypatch.setattr(deepseek_spec, "_client", Client)
    return calls


def test_example_accepts_chinese_sizes_exact_spacing_and_auto(monkeypatch):
    raw = {"题目": {"font": {"name": "黑体", "size": "三号字"}, "paragraph": {"alignment": "居中"}},
           "正文": {"font": {"name": "宋体", "size": "小四"},
                  "paragraph": {"first_line_indent_chars": "2字", "line_spacing": "固定值22", "space_after": 0}}}
    calls = _client(monkeypatch, [_response(json.dumps(raw, ensure_ascii=False))])
    rule = deepseek_spec.extract_ruleset(TEXT)
    assert rule.name == "格式审查规则"
    assert rule.title.font.size == 16
    assert rule.title.paragraph.alignment == "center"
    assert rule.body.font.size == 12
    assert rule.body.paragraph.first_line_indent_chars == 2
    assert rule.body.paragraph.line_spacing_kind == "exact"
    assert rule.body.paragraph.line_spacing == 22
    assert rule.body.paragraph.space_after is None
    assert len(calls) == 1


def test_fixed_spacing_is_preserved_when_model_returns_only_number(monkeypatch):
    raw = {"name": "正文行距", "body": {"paragraph": {"line_spacing": 22}}}
    _client(monkeypatch, [_response(json.dumps(raw, ensure_ascii=False))])
    rule = deepseek_spec.extract_ruleset("正文：行间距：固定值22。")
    assert rule.body.paragraph.line_spacing == 22
    assert rule.body.paragraph.line_spacing_kind == "exact"


def test_invalid_first_response_is_retried_once(monkeypatch):
    valid = {"name": "标题字号", "title": {"font": {"size": "三号"}}}
    calls = _client(monkeypatch, [_response("{"), _response(json.dumps(valid, ensure_ascii=False))])
    rule = deepseek_spec.extract_ruleset("题目三号字")
    assert rule.title.font.size == 16
    assert len(calls) == 2
    assert "未通过校验" in calls[1]["messages"][-1]["content"]


def test_auto_on_same_line_only_disables_matching_scope(monkeypatch):
    raw = {"name": "间距", "title": {"paragraph": {"space_after": 0}},
           "body": {"paragraph": {"space_after": 0}}}
    _client(monkeypatch, [_response(json.dumps(raw, ensure_ascii=False))])
    rule = deepseek_spec.extract_ruleset("题目：段后间距0。正文：段后间距自动。")
    assert rule.title.paragraph.space_after == 0
    assert rule.body.paragraph.space_after is None


def test_still_invalid_after_retry_reports_field(monkeypatch):
    invalid = json.dumps({"name": "格式", "body": {"font": {"size": "未知字号"}}}, ensure_ascii=False)
    _client(monkeypatch, [_response(invalid), _response(invalid)])
    with pytest.raises(ValueError, match="body.font.size"):
        deepseek_spec.extract_ruleset("正文未知字号")
