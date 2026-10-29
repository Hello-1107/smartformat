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
    TemplateDocumentChecks,
    TemplateRegionRule,
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
    if expected is None:
        return True
    if actual is None:
        return False
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
            severity="unknown" if actual is None else "error",
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
    if rule.line_spacing is not None and (not _num_close(
        para.line_spacing, rule.line_spacing, 0.15
    ) or para.line_spacing_kind != (rule.line_spacing_kind or "multiple")):
        _add(
            v, scope, "paragraph", "line_spacing", {"kind": rule.line_spacing_kind or "multiple", "value": rule.line_spacing},
            {"kind": para.line_spacing_kind, "value": para.line_spacing} if para.line_spacing is not None else None,
            f"行距应为 {rule.line_spacing}（{rule.line_spacing_kind or 'multiple'}），实际为 {para.line_spacing}（{para.line_spacing_kind}）",
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
            if not para.numbered and not re.match(r"^\s*(?:\d|[一二三四五六七八九十]+[、.．])", para.text or ""):
                _add(
                    v, "heading_structure", "heading_structure", "require_numbered",
                    True, False,
                    f"标题「{para.text[:30]}」缺少编号",
                    para,
                )


def _resolve_scope(
    para: ParsedParagraph, ruleset: RuleSet
) -> tuple[str, ScopeRule] | None:
    if para.is_title:
        return ("title", ruleset.title) if ruleset.title is not None else None
    if para.level is not None and ruleset.headings:
        key = f"h{para.level}"
        scope_rule = ruleset.headings.get(key)  # type: ignore[union-attr]
        if scope_rule is not None:
            return key, scope_rule
    if para.level is None and ruleset.body is not None:
        return "body", ruleset.body
    return None


_ANCHOR_PREFIX = re.compile(
    r"^\s*(?:第\s*[0-9一二三四五六七八九十百]+\s*[章节篇部]|"
    r"[0-9]+(?:[.．-][0-9]+)*\s*[、.．]?|[一二三四五六七八九十]+[、.．])\s*"
)
_CAPTION = re.compile(r"^\s*(?:图|表)\s*[0-9一二三四五六七八九十]+(?:[-—.．][0-9]+)*")
_CODE_HINT = re.compile(r"(?:[{};]|=>|==|!=|\b(?:class|public|private|function|const|let|var|import|return)\b)")


def _normal_anchor(text: str) -> str:
    return re.sub(r"[\s\u3000]+", "", text).strip("：:、,.．。-—_").casefold()


def _semantic_anchor(text: str) -> str:
    return _normal_anchor(_ANCHOR_PREFIX.sub("", text))


def _compatible_anchor(paragraph: ParsedParagraph, region: TemplateRegionRule) -> bool:
    return paragraph.is_title if region.level == 0 else paragraph.level == region.level


def _is_prose(paragraph: ParsedParagraph) -> bool:
    text = paragraph.text.strip()
    if paragraph.role != "body" or paragraph.level is not None or paragraph.is_title or len(text) < 8 or _CAPTION.match(text):
        return False
    if _CODE_HINT.search(text) and sum(text.count(char) for char in "{};()=") >= 3:
        return False
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False
    cjk = len(re.findall(r"[\u3400-\u9fff]", compact))
    letters = len(re.findall(r"[A-Za-z]", compact))
    return cjk / len(compact) >= 0.12 or (letters / len(compact) >= 0.65 and not _CODE_HINT.search(text))


def _add_template_issue(
    violations: list[Violation], region: TemplateRegionRule | None, field: str,
    expected: object, actual: object, message: str,
    paragraph: ParsedParagraph | None = None,
) -> None:
    violations.append(Violation(
        scope=f"template_region:{region.label[:40]}" if region else "template_structure",
        category="template_structure" if field not in {"anchor_text"} else "template_content",
        field=field,
        expected=expected,
        actual=actual,
        message=message,
        paragraph_index=paragraph.index if paragraph else None,
        paragraph_text=paragraph.text[:60] if paragraph and paragraph.text else None,
        severity="error",
    ))


def _check_region_style(
    violations: list[Violation], region: TemplateRegionRule,
    heading: ParsedParagraph, body_end: int, parsed: ParsedDocument,
) -> None:
    scope = f"template_region:{region.label[:40]}"
    if region.heading_style is not None:
        if region.heading_style.font is not None:
            _check_font(violations, scope, heading.font, region.heading_style.font, heading)
        if region.heading_style.paragraph is not None:
            _check_paragraph(violations, scope, heading, region.heading_style.paragraph)
    if region.body_style is None:
        return
    for paragraph in parsed.paragraphs[heading.index + 1:body_end]:
        if not _is_prose(paragraph):
            continue
        if region.body_style.font is not None:
            _check_font(violations, scope, paragraph.font, region.body_style.font, paragraph)
        if region.body_style.paragraph is not None:
            _check_paragraph(violations, scope, paragraph, region.body_style.paragraph)


def _check_template_regions(
    violations: list[Violation], parsed: ParsedDocument,
    regions: list[TemplateRegionRule],
) -> None:
    anchors = [
        paragraph for paragraph in parsed.paragraphs
        if paragraph.text.strip() and (paragraph.is_title or paragraph.level is not None)
    ]
    consumed: set[int] = set()
    matched: list[tuple[TemplateRegionRule, int, ParsedParagraph]] = []
    cursor = 0

    for region in regions:
        expected_key = _normal_anchor(region.anchor)
        semantic_key = _semantic_anchor(region.anchor)
        compatible = [
            index for index in range(cursor, len(anchors))
            if index not in consumed and _compatible_anchor(anchors[index], region)
        ]
        exact = [index for index in compatible if _normal_anchor(anchors[index].text) == expected_key]
        semantic = [index for index in compatible if _semantic_anchor(anchors[index].text) == semantic_key]
        found = (exact or semantic or (compatible[:1] if region.mode == "variable" else []))

        if not found:
            previous = next((
                index for index in range(0, cursor)
                if index not in consumed and _compatible_anchor(anchors[index], region)
                and _semantic_anchor(anchors[index].text) == semantic_key
            ), None)
            if previous is not None:
                paragraph = anchors[previous]
                consumed.add(previous)
                matched.append((region, previous, paragraph))
                if region.mode != "ignore":
                    _add_template_issue(
                        violations, region, "region_order", region.anchor, paragraph.text,
                        f"章节「{region.label}」出现顺序与模板不一致", paragraph,
                    )
                continue
            if region.required and region.mode != "ignore":
                _add_template_issue(
                    violations, region, "missing_region", region.anchor, None,
                    f"缺少模板要求的章节「{region.label}」",
                )
            continue

        anchor_position = found[0]
        paragraph = anchors[anchor_position]
        consumed.add(anchor_position)
        matched.append((region, anchor_position, paragraph))
        cursor = anchor_position + 1
        if region.mode == "fixed" and _normal_anchor(paragraph.text) != expected_key:
            _add_template_issue(
                violations, region, "anchor_text", region.anchor, paragraph.text,
                f"章节标题应为「{region.anchor}」，实际为「{paragraph.text}」", paragraph,
            )

    active_levels = {region.level for region in regions if region.mode != "ignore"}
    positive_levels = {level for level in active_levels if level > 0}
    # 模板通常只列出推荐的小节，待审报告允许在章内继续展开；仅把新增的
    # 文档大标题或最高层级章节视为结构差异，避免把实现细节误报为多余章节。
    extra_levels = ({0} if 0 in active_levels else set()) | ({min(positive_levels)} if positive_levels else set())
    for index, paragraph in enumerate(anchors):
        level = 0 if paragraph.is_title else int(paragraph.level or 0)
        if index not in consumed and level in extra_levels:
            _add_template_issue(
                violations, None, "extra_region", "模板中已配置的章节", paragraph.text,
                f"发现模板之外的章节「{paragraph.text[:60]}」", paragraph,
            )

    for region, anchor_position, paragraph in matched:
        if region.mode == "ignore" or not region.check_format:
            continue
        body_end = anchors[anchor_position + 1].index if anchor_position + 1 < len(anchors) else len(parsed.paragraphs)
        _check_region_style(violations, region, paragraph, body_end, parsed)


def _toc_text(text: str) -> str:
    return re.sub(r"(?:\t|[.．·…\s])+(?:\d+|[IVXLCDM]+)\s*$", "", text, flags=re.I).strip()


_CAPTION_NUMBER = re.compile(r"^\s*([图表])\s*([0-9]+(?:[-—.．][0-9]+)*)")
_CAPTION_REFERENCE = re.compile(r"([图表])\s*([0-9]+(?:[-—.．][0-9]+)*)")


def _caption_key(kind: str, number: str) -> tuple[str, str]:
    return kind, re.sub(r"[-—．]", ".", number)


def _check_scope_style(
    violations: list[Violation], scope: str, paragraph: ParsedParagraph,
    style: ScopeRule | None,
) -> None:
    if style is None:
        return
    if style.font is not None:
        _check_font(violations, scope, paragraph.font, style.font, paragraph)
    if style.paragraph is not None:
        _check_paragraph(violations, scope, paragraph, style.paragraph)


def _check_toc(
    violations: list[Violation], parsed: ParsedDocument,
    checks: TemplateDocumentChecks,
) -> None:
    toc = [p for p in parsed.paragraphs if p.role == "toc" and p.text.strip()]
    if not toc:
        _add_template_issue(violations, None, "missing_toc", "存在目录", None, "待审文档缺少可识别的目录")
        violations[-1].category = "toc"
        return
    toc_by_key: dict[str, list[ParsedParagraph]] = {}
    for paragraph in toc:
        key = _semantic_anchor(_toc_text(paragraph.text))
        if key:
            toc_by_key.setdefault(key, []).append(paragraph)
    for expected in checks.toc_entries:
        key = _semantic_anchor(expected)
        if key and key not in toc_by_key:
            _add_template_issue(
                violations, None, "toc_entry_missing", expected, None,
                f"目录缺少模板要求的条目「{expected}」",
            )
            violations[-1].category = "toc"
    heading_keys = {
        _semantic_anchor(p.text) for p in parsed.paragraphs
        if p.text.strip() and (p.is_title or p.level is not None)
    }
    for key, entries in toc_by_key.items():
        if key not in heading_keys:
            paragraph = entries[0]
            _add_template_issue(
                violations, None, "toc_without_heading", "目录项在正文中有对应标题",
                _toc_text(paragraph.text), f"目录项「{_toc_text(paragraph.text)}」未找到对应正文标题", paragraph,
            )
            violations[-1].category = "toc"


def _check_captions(
    violations: list[Violation], parsed: ParsedDocument,
    checks: TemplateDocumentChecks,
) -> None:
    captions: dict[tuple[str, str], list[ParsedParagraph]] = {}
    enabled = {"图": checks.check_figure_numbering, "表": checks.check_table_numbering}
    for paragraph in parsed.paragraphs:
        match = _CAPTION_NUMBER.match(paragraph.text)
        if paragraph.role not in {"figure_caption", "table_caption"} or not match:
            continue
        captions.setdefault(_caption_key(match.group(1), match.group(2)), []).append(paragraph)
        style = checks.figure_caption_style if match.group(1) == "图" else checks.table_caption_style
        if enabled[match.group(1)]:
            _check_scope_style(violations, f"{match.group(1)}题注", paragraph, style)

    for (kind, number), items in captions.items():
        if enabled[kind] and len(items) > 1:
            _add_template_issue(
                violations, None, "duplicate_caption", f"{kind}{number} 仅出现一次",
                len(items), f"{kind}{number} 的题注重复", items[0],
            )
            violations[-1].category = "caption"
    for kind, should_check in enabled.items():
        if not should_check:
            continue
        sequences: dict[str, set[int]] = {}
        for prefix, number in captions:
            if prefix != kind:
                continue
            parts = number.split(".")
            sequences.setdefault(".".join(parts[:-1]), set()).add(int(parts[-1]))
        for prefix, values in sequences.items():
            expected = set(range(1, max(values) + 1)) if values else set()
            missing = sorted(expected - values)
            if missing:
                label = f"{prefix}." if prefix else ""
                _add_template_issue(
                    violations, None, "caption_number_gap",
                    [f"{kind}{label}{value}" for value in sorted(expected)],
                    [f"{kind}{label}{value}" for value in sorted(values)],
                    f"{kind}题注编号不连续，缺少 {', '.join(f'{kind}{label}{value}' for value in missing)}",
                )
                violations[-1].category = "caption"

    for paragraph in parsed.paragraphs:
        if paragraph.role in {"toc", "figure_caption", "table_caption", "code"}:
            continue
        for match in _CAPTION_REFERENCE.finditer(paragraph.text):
            key = _caption_key(match.group(1), match.group(2))
            if enabled[key[0]] and key not in captions:
                _add_template_issue(
                    violations, None, "caption_reference_missing", f"存在{key[0]}{key[1]}题注",
                    paragraph.text[:80], f"正文引用了{key[0]}{key[1]}，但未找到对应题注", paragraph,
                )
                violations[-1].category = "caption"


def _check_template_document_features(
    violations: list[Violation], parsed: ParsedDocument,
    checks: TemplateDocumentChecks,
) -> None:
    if checks.check_toc:
        _check_toc(violations, parsed, checks)
    if checks.check_figure_numbering or checks.check_table_numbering:
        _check_captions(violations, parsed, checks)
    if checks.check_code_style:
        for paragraph in parsed.paragraphs:
            if paragraph.role == "code" and paragraph.text.strip():
                _check_scope_style(violations, "代码块", paragraph, checks.code_style)


def run_check(parsed: ParsedDocument, ruleset: RuleSet) -> tuple[list[Violation], CheckSummary]:
    """对解析结果执行规则，返回 (违规列表, 汇总)。"""
    violations: list[Violation] = []
    applicable = False
    if not ruleset.has_constraints():
        raise ValueError("规则没有有效检查项，请先配置规则")

    if ruleset.page is not None and parsed.sections:
        applicable = any(value is not None for value in ruleset.page.model_dump().values())
        for section in parsed.sections:
            start = len(violations)
            _check_page(violations, section, ruleset.page)
            for violation in violations[start:]:
                violation.section_index = section.index
                violation.message = f"第 {section.index + 1} 节：{violation.message}"

    for para in parsed.paragraphs:
        if not para.text.strip():
            continue
        resolved = _resolve_scope(para, ruleset)
        if resolved is None:
            continue
        scope, scope_rule = resolved
        applicable = applicable or any(value is not None for section in (scope_rule.font, scope_rule.paragraph) if section is not None for key, value in section.model_dump().items() if key != "line_spacing_kind")
        if scope_rule.font is not None:
            if para.runs:
                for index, run in enumerate(para.runs):
                    start = len(violations)
                    _check_font(violations, scope, run.font, scope_rule.font, para)
                    for violation in violations[start:]:
                        violation.run_index = index
                        violation.paragraph_text = run.text[:60]
            else:
                _check_font(violations, scope, para.font, scope_rule.font, para)
        if scope_rule.paragraph is not None:
            _check_paragraph(violations, scope, para, scope_rule.paragraph)

    if ruleset.template_regions:
        active_regions = [region for region in ruleset.template_regions if region.mode != "ignore"]
        if active_regions:
            applicable = True
            _check_template_regions(violations, parsed, ruleset.template_regions)

    if ruleset.template_checks is not None and any((
        ruleset.template_checks.check_toc,
        ruleset.template_checks.check_figure_numbering,
        ruleset.template_checks.check_table_numbering,
        ruleset.template_checks.check_code_style,
    )):
        applicable = True
        _check_template_document_features(violations, parsed, ruleset.template_checks)

    if ruleset.heading_structure is not None:
        applicable = applicable or ruleset.heading_structure.max_level is not None or ruleset.heading_structure.require_numbered is True
        _check_heading_structure(violations, parsed, ruleset.heading_structure)

    if not applicable:
        _add(violations, "coverage", "coverage", "applicable_content", "存在可检查的文档区域", None, "没有匹配到可检查的文档区域，不能确认合规")

    summary = _summarize(violations)
    return violations, summary


def _summarize(violations: list[Violation]) -> CheckSummary:
    by_category = dict(Counter(v.category for v in violations))
    return CheckSummary(
        total=len(violations),
        by_category=by_category,
        compliant=len(violations) == 0,
        unknown=sum(v.severity == "unknown" for v in violations),
        status="pass" if not violations else "unknown" if all(v.severity == "unknown" for v in violations) else "fail",
    )
