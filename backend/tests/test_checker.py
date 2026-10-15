"""规则引擎单元测试（纯确定性，无 IO / 无网络）。"""

from app.schemas.document import FontInfo, ParsedDocument, ParsedParagraph
from app.schemas.rule import FontRule, PageRule, ParagraphRule, RuleSet, ScopeRule
from app.services.checker import run_check


def _para(**kwargs) -> ParsedParagraph:
    defaults = dict(
        index=0, text="正文段落", style_name="Normal", level=None, font=FontInfo()
    )
    defaults.update(kwargs)
    return ParsedParagraph(**defaults)


def test_font_size_violation() -> None:
    doc = ParsedDocument(
        filename="a.docx",
        paragraphs=[
            _para(font=FontInfo(name="宋体", size=14, bold=False)),
        ],
    )
    ruleset = RuleSet(
        name="正文规则",
        body=ScopeRule(font=FontRule(name="宋体", size=12)),
    )
    violations, summary = run_check(doc, ruleset)
    assert summary.total == 1
    assert violations[0].field == "size"
    assert violations[0].expected == 12
    assert violations[0].actual == 14


def test_font_name_alias_match() -> None:
    doc = ParsedDocument(
        filename="a.docx",
        paragraphs=[_para(font=FontInfo(name="SimSun", size=12))],
    )
    ruleset = RuleSet(name="r", body=ScopeRule(font=FontRule(name="宋体", size=12)))
    _, summary = run_check(doc, ruleset)
    assert summary.compliant is True


def test_paragraph_rules() -> None:
    doc = ParsedDocument(
        filename="a.docx",
        paragraphs=[_para(alignment="left", line_spacing=1.0, first_line_indent_chars=0)],
    )
    ruleset = RuleSet(
        name="r",
        body=ScopeRule(
            paragraph=ParagraphRule(
                alignment="justify", line_spacing=1.5, first_line_indent_chars=2
            )
        ),
    )
    violations, summary = run_check(doc, ruleset)
    fields = {v.field for v in violations}
    assert {"alignment", "line_spacing", "first_line_indent_chars"} <= fields


def test_page_rules() -> None:
    from app.schemas.document import ParsedSection

    doc = ParsedDocument(
        filename="a.docx",
        sections=[
            ParsedSection(index=0, paper="A4", margin_left_cm=2.0, margin_right_cm=2.0)
        ],
        paragraphs=[],
    )
    ruleset = RuleSet(
        name="r",
        page=PageRule(paper="A4", margin_left_cm=3.17, margin_right_cm=3.17),
    )
    violations, _ = run_check(doc, ruleset)
    fields = {v.field for v in violations}
    assert {"margin_left_cm", "margin_right_cm"} <= fields


def test_heading_structure_max_level() -> None:
    doc = ParsedDocument(
        filename="a.docx",
        paragraphs=[
            _para(index=0, text="1 引言", level=1),
            _para(index=1, text="1.1 背景", level=2),
            _para(index=2, text="1.1.1 细节", level=3),
        ],
    )
    ruleset = RuleSet(
        name="r",
        heading_structure={"max_level": 2},
    )
    violations, _ = run_check(doc, ruleset)
    assert any(v.field == "max_level" for v in violations)


def test_compliant_when_no_violations() -> None:
    doc = ParsedDocument(
        filename="a.docx",
        paragraphs=[_para(font=FontInfo(name="宋体", size=12))],
    )
    ruleset = RuleSet(name="r", body=ScopeRule(font=FontRule(name="宋体", size=12)))
    _, summary = run_check(doc, ruleset)
    assert summary.compliant is True
