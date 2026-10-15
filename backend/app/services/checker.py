"""确定性规则引擎：逐项核对解析后的文档是否满足结构化规则。

这里是唯一负责「是否合规」的代码，纯确定性判断，不调用 AI。
所有比较都带合理容差，避免浮点/单位换算误差造成误报。
"""

from __future__ import annotations

import re
from collections import Counter

from app.schemas.check import CheckSummary, Violation
from app.schemas.document import FontInfo, ParsedDocument, ParsedParagraph, ParsedSection
from app.schemas.rule import (
    FontRule,
    HeadingStructureRule,
    PageRule,
    ParagraphRule,
    RuleSet,
    ScopeRule,
)

# 常见中文字体名 ↔ 英文字体名 归一化映射
_FONT_ALIASES: dict[str, str] = {
    "simsun": "宋体",
    "宋体": "宋体",
    "nsimsun": "新宋体",
    "新宋体": "新宋体",
    "simhei": "黑体",
    "黑体": "黑体",
    "microsoft yahei": "微软雅黑",
    "微软雅黑": "微软雅黑",
    "kaiti": "楷体",
    "楷体": "楷体",
    "kaiti gb2312": "楷体_gb2312",
    "fangsong": "仿宋",
    "仿宋": "仿宋",
    "仿宋_gb2312": "仿宋_gb2312",
    "dengxian": "等线",
    "等线": "等线",
    "times new roman": "times new roman",
    "arial": "arial",
    "calibri": "calibri",
    "cambria": "cambria",
}

_FLOAT_TOLERANCE = 0.01


def _norm_font(name: str | None) -> str | None:
    if not name:
        return None
    key = name.strip().lower()
    return _FONT_ALIASES.get(key, key)


def _fonts_equal(actual: str | None, expected: str | None) -> bool:
    if expected is None:
        return True
    return _norm_font(actual) == _norm_font(expected)


def _num_close(actual: float | None, expected: float | None, tol: float) -> bool:
    if expected is None or actual is None:
        return True
    return abs(actual - expected) <= tol


def _bool_match(actual: bool | None, expected: bool | None) -> bool:
    if expected is None:
        return True
    return (actual is True) == expected  # None 视为 False


def _color_match(actual: str | None, expected: str | None) -> bool:
    if expected is None:
        return True
    a = (actual or "").lstrip("#").lower()
    e = expected.lstrip("#").lower()
    return a == e


def _add(
    violations: list[Violation],
    scope: str,
    category: str,
    field: str,
    expected: object,
    actual: object,
    message: str,
    paragraph: ParsedParagraph | None = None,
) -> None:
    violations.append(
        Violation(
            scope=scope,
            category=category,
            field=field,
            expected=expected,
            actual=actual,
            message=message,
            paragraph_index=paragraph.index if paragraph else None,
            paragraph_text=(paragraph.text[:60] if paragraph and paragraph.text else None),
            severity="error",
        )
    )


def _check_font(
    v: list[Violation],
    scope: str,
    font: FontInfo,
    rule: FontRule,
    paragraph: ParsedParagraph | None,
) -> None:
    if rule.name is not None and not _fonts_equal(font.name, rule.name):
        _add(
            v, scope, "font", "name", rule.name, font.name,
            f"中文字体应为「{rule.name}」，实际为「{font.name or '未设置'}」",
            paragraph,
        )
    if rule.ascii_name is not None and not _fonts_equal(font.ascii_name, rule.ascii_name):
        _add(
            v, scope, "font", "ascii_name", rule.ascii_name, font.ascii_name,
            f"西文字体应为「{rule.ascii_name}」，实际为「{font.ascii_name or '未设置'}」",
            paragraph,
        )
    if rule.size is not None and not _num_close(font.size, rule.size, 0.5):
        _add(
            v, scope, "font", "size", rule.size, font.size,
            f"字号应为 {rule.size}pt，实际为 {font.size}pt",
            paragraph,
        )
    if rule.bold is not None and not _bool_match(font.bold, rule.bold):
        _add(
            v, scope, "font", "bold", rule.bold, bool(font.bold),
            f"加粗应为 {rule.bold}，实际为 {bool(font.bold)}",
            paragraph,
        )
    if rule.italic is not None and not _bool_match(font.italic, rule.italic):
        _add(
            v, scope, "font", "italic", rule.italic, bool(font.italic),
            f"斜体应为 {rule.italic}，实际为 {bool(font.italic)}",
            paragraph,
        )
    if rule.color is not None and not _color_match(font.color, rule.color):
        _add(
            v, scope, "font", "color", rule.color, font.color,
            f"字体颜色应为 #{rule.color}，实际为 #{font.color or '未设置'}",
            paragraph,
        )


def _check_paragraph(
    v: list[Violation],
    scope: str,
    para: ParsedParagraph,
    rule: ParagraphRule,
) -> None:
    if rule.alignment is not None and para.alignment != rule.alignment:
        _add(
            v, scope, "paragraph", "alignment", rule.alignment, para.alignment,
            f"对齐方式应为「{rule.alignment}」，实际为「{para.alignment or '未设置'}」",
            para,
        )
    if rule.line_spacing is not None and not _num_close(
        para.line_spacing, rule.line_spacing, 0.15
    ):
        _add(
            v, scope, "paragraph", "line_spacing", rule.line_spacing, para.line_spacing,
            f"行距应为 {rule.line_spacing} 倍，实际为 {para.line_spacing} 倍",
            para,
        )
    if rule.space_before is not None and not _num_close(
        para.space_before, rule.space_before, 2.0
    ):
        _add(
            v, scope, "paragraph", "space_before", rule.space_before, para.space_before,
            f"段前间距应为 {rule.space_before}pt，实际为 {para.space_before}pt",
            para,
        )
    if rule.space_after is not None and not _num_close(
        para.space_after, rule.space_after, 2.0
    ):
        _add(
            v, scope, "paragraph", "space_after", rule.space_after, para.space_after,
            f"段后间距应为 {rule.space_after}pt，实际为 {para.space_after}pt",
            para,
        )
    if rule.first_line_indent_chars is not None and not _num_close(
        para.first_line_indent_chars, rule.first_line_indent_chars, 0.3
    ):
        _add(
            v, scope, "paragraph", "first_line_indent_chars",
            rule.first_line_indent_chars, para.first_line_indent_chars,
            f"首行缩进应为 {rule.first_line_indent_chars} 字符，"
            f"实际为 {para.first_line_indent_chars} 字符",
            para,
        )
    if rule.numbered is not None and not _bool_match(para.numbered, rule.numbered):
        _add(
            v, scope, "paragraph", "numbered", rule.numbered, para.numbered,
            f"是否编号应为 {rule.numbered}，实际为 {para.numbered}",
            para,
        )
    if rule.bullet is not None and not _bool_match(para.bullet, rule.bullet):
        _add(
            v, scope, "paragraph", "bullet", rule.bullet, para.bullet,
            f"是否项目符号应为 {rule.bullet}，实际为 {para.bullet}",
            para,
        )


def _check_page(
    v: list[Violation], section: ParsedSection, rule: PageRule
) -> None:
    if rule.paper is not None and (
        section.paper is None or section.paper.lower() != rule.paper.lower()
    ):
        _add(
            v, "page", "page", "paper", rule.paper, section.paper,
            f"纸张应为 {rule.paper}，实际为 {section.paper or '未知'}",
        )
    pairs = [
        ("width_cm", "页面宽度", 0.3),
        ("height_cm", "页面高度", 0.3),
        ("margin_top_cm", "上边距", 0.2),
        ("margin_bottom_cm", "下边距", 0.2),
        ("margin_left_cm", "左边距", 0.2),
        ("margin_right_cm", "右边距", 0.2),
        ("header_distance_cm", "页眉距离", 0.2),
        ("footer_distance_cm", "页脚距离", 0.2),
    ]
    for field, label, tol in pairs:
        expected = getattr(rule, field)
        if expected is None:
            continue
        actual = getattr(section, field)
        if not _num_close(actual, expected, tol):
            _add(
                v, "page", "page", field, expected, actual,
                f"{label}应为 {expected}cm，实际为 {actual}cm",
            )


def _check_heading_structure(
    v: list[Violation],
    doc: ParsedDocument,
    rule: HeadingStructureRule,
) -> None:
    headings = [p for p in doc.paragraphs if p.level is not None]
    if rule.max_level is not None:
        max_level = max((p.level or 0) for p in headings) if headings else 0
        if max_level > rule.max_level:
            _add(
                v, "heading_structure", "heading_structure", "max_level",
                rule.max_level, max_level,
                f"标题最大层级不应超过 {rule.max_level} 级，实际出现 {max_level} 级",
            )
    if rule.require_numbered:
        for para in headings:
            if not re.match(r"^\s*\d", para.text or ""):
                _add(
                    v, "heading_structure", "heading_structure", "require_numbered",
                    True, False,
                    f"标题「{para.text[:30]}」缺少编号",
                    para,
                )


def _resolve_scope(
    para: ParsedParagraph, ruleset: RuleSet
) -> tuple[str, ScopeRule] | None:
    if para.level is not None and ruleset.headings:
        key = f"h{para.level}"
        scope_rule = ruleset.headings.get(key)  # type: ignore[union-attr]
        if scope_rule is not None:
            return key, scope_rule
    if para.level is None and ruleset.body is not None:
        return "body", ruleset.body
    return None


def run_check(parsed: ParsedDocument, ruleset: RuleSet) -> tuple[list[Violation], CheckSummary]:
    """对解析结果执行规则，返回 (违规列表, 汇总)。"""
    violations: list[Violation] = []

    if ruleset.page is not None and parsed.sections:
        _check_page(violations, parsed.sections[0], ruleset.page)

    for para in parsed.paragraphs:
        resolved = _resolve_scope(para, ruleset)
        if resolved is None:
            continue
        scope, scope_rule = resolved
        if scope_rule.font is not None:
            _check_font(violations, scope, para.font, scope_rule.font, para)
        if scope_rule.paragraph is not None:
            _check_paragraph(violations, scope, para, scope_rule.paragraph)

    if ruleset.heading_structure is not None:
        _check_heading_structure(violations, parsed, ruleset.heading_structure)

    summary = _summarize(violations)
    return violations, summary


def _summarize(violations: list[Violation]) -> CheckSummary:
    by_category = dict(Counter(v.category for v in violations))
    return CheckSummary(
        total=len(violations),
        by_category=by_category,
        compliant=len(violations) == 0,
    )
