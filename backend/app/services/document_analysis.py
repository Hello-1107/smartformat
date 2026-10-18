"""文档结构、版本复审及跨文档字段核对；所有比较均有原文出处。"""

import json
import re
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher

from app.schemas.analysis import (
    CrossDocumentResult, CrossFieldResult, FieldSpec, FieldValue, Finding,
    SourceRef, StructureCheckResult, VersionCompareResult,
)
from app.schemas.content_review import ContentParagraph
from app.schemas.document import ParsedDocument, ParsedParagraph
from app.schemas.rule import RuleSet
from app.services.checker import run_check


def _source(document_id: int, index: int | None, quote: str | None) -> SourceRef:
    return SourceRef(document_id=document_id, paragraph_index=index, quote=quote)


def _heading_name(text: str) -> str:
    return re.sub(r"^\s*(?:第?[一二三四五六七八九十]+[章节]|[一二三四五六七八九十\d]+[.．、）)]|\d+\s+)?", "", text).strip().casefold()


def check_structure(
    document_id: int, parsed: ParsedDocument, required: list[str], require_order: bool,
) -> StructureCheckResult:
    headings = [p for p in parsed.paragraphs if p.level is not None or p.is_title]
    names = [_heading_name(p.text) for p in headings]
    findings: list[Finding] = []
    found_positions: list[int] = []
    for expected in required:
        name = _heading_name(expected)
        if not name:
            raise ValueError("必需章节名称不能为空")
        matches = [i for i, candidate in enumerate(names) if candidate == name]
        if not matches:
            findings.append(Finding(category="章节", status="missing", message=f"缺少必需章节「{expected}」"))
        elif len(matches) > 1:
            findings.append(Finding(category="章节", status="ambiguous", message=f"章节「{expected}」出现多次，请人工确认", sources=[_source(document_id, headings[i].index, headings[i].text) for i in matches]))
        else:
            found_positions.append(matches[0])
    if require_order and found_positions != sorted(found_positions):
        findings.append(Finding(category="章节", status="out_of_order", message="必需章节顺序与配置不一致", sources=[_source(document_id, headings[i].index, headings[i].text) for i in found_positions]))

    captions: dict[tuple[str, str], list[ParsedParagraph]] = {}
    references: dict[tuple[str, str], list[ParsedParagraph]] = {}
    marker = re.compile(r"([图表])\s*(\d+(?:[.\-]\d+)*)")
    for paragraph in parsed.paragraphs:
        text = paragraph.text.strip()
        if not text:
            continue
        caption = marker.match(text)
        if caption:
            key = (caption.group(1), caption.group(2).replace("-", "."))
            captions.setdefault(key, []).append(paragraph)
            continue
        for match in marker.finditer(text):
            key = (match.group(1), match.group(2).replace("-", "."))
            references.setdefault(key, []).append(paragraph)
    for key, items in captions.items():
        if len(items) > 1:
            findings.append(Finding(category="图表", status="duplicate", message=f"{key[0]} {key[1]} 的题注重复", sources=[_source(document_id, p.index, p.text) for p in items]))
    for key, items in references.items():
        if key not in captions:
            findings.append(Finding(category="图表", status="missing", message=f"正文引用了{key[0]} {key[1]}，未找到对应题注", sources=[_source(document_id, p.index, p.text) for p in items[:5]]))
    for kind in ("图", "表"):
        numbers = sorted({int(number) for prefix, number in captions if prefix == kind and number.isdigit()})
        if numbers and numbers != list(range(1, max(numbers) + 1)):
            findings.append(Finding(category="图表", status="gap", message=f"{kind}题注的整数编号不连续，请核对缺号"))
    return StructureCheckResult(document_id=document_id, headings_found=[p.text for p in headings], findings=findings)


def _alignment(original: list[ParsedParagraph], revised: list[ParsedParagraph]) -> dict[int, int]:
    old_text = [p.text.strip() for p in original]
    new_text = [p.text.strip() for p in revised]
    matcher = SequenceMatcher(None, old_text, new_text, autojunk=False)
    aligned: dict[int, int] = {}
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op == "equal":
            aligned.update({original[a0 + offset].index: revised[b0 + offset].index for offset in range(a1-a0)})
        elif op == "replace" and a1-a0 == b1-b0:
            for old, new in zip(original[a0:a1], revised[b0:b1]):
                if SequenceMatcher(None, old.text, new.text).ratio() >= 0.6:
                    aligned[old.index] = new.index
    return aligned


def _violation_key(violation: object, paragraph_index: int | None) -> tuple[str, str, str, str, int | None]:
    return (
        violation.scope, violation.category, violation.field,
        json.dumps(violation.expected, ensure_ascii=False, sort_keys=True), paragraph_index,
    )


def compare_versions(
    original_id: int, revised_id: int, rule_id: int,
    original: ParsedDocument, revised: ParsedDocument, ruleset: RuleSet,
) -> VersionCompareResult:
    old_issues, _old_summary = run_check(original, ruleset)
    new_issues, _new_summary = run_check(revised, ruleset)
    aligned = _alignment(original.paragraphs, revised.paragraphs)
    old_paragraphs = {p.index: p for p in original.paragraphs}
    new_paragraphs = {p.index: p for p in revised.paragraphs}
    findings: list[Finding] = []
    # 文字变化与问题变化分别报告；不根据段落位置猜测已解决。
    matcher = SequenceMatcher(None, [p.text for p in original.paragraphs], [p.text for p in revised.paragraphs], autojunk=False)
    for op, a0, a1, b0, b1 in matcher.get_opcodes():
        if op == "equal":
            continue
        sources = [_source(original_id, p.index, p.text[:200]) for p in original.paragraphs[a0:a1][:3]]
        sources += [_source(revised_id, p.index, p.text[:200]) for p in revised.paragraphs[b0:b1][:3]]
        findings.append(Finding(category="文字变化", status=op, message={"replace":"文字已修改", "insert":"新增文字", "delete":"删除文字"}[op], sources=sources))

    available = {}
    for issue in new_issues:
        key = _violation_key(issue, issue.paragraph_index)
        available.setdefault(key, []).append(issue)
    for issue in old_issues:
        old_index = issue.paragraph_index
        mapped = aligned.get(old_index) if old_index is not None else None
        key = _violation_key(issue, mapped)
        matches = available.get(key, []) if old_index is None or mapped is not None else []
        if matches:
            new_issue = matches.pop()
            status = "remaining"
            sources = [_source(original_id, old_index, issue.paragraph_text)]
            sources.append(_source(revised_id, new_issue.paragraph_index, new_issue.paragraph_text))
        elif old_index is not None and mapped is None:
            status = "uncertain"
            sources = [_source(original_id, old_index, issue.paragraph_text)]
        else:
            status = "resolved"
            sources = [_source(original_id, old_index, issue.paragraph_text)]
            if mapped is not None:
                paragraph = new_paragraphs.get(mapped)
                if paragraph:
                    sources.append(_source(revised_id, mapped, paragraph.text))
        findings.append(Finding(category="格式复审", status=status, message=issue.message, sources=sources))
    for issues in available.values():
        for issue in issues:
            findings.append(Finding(category="格式复审", status="new", message=issue.message, sources=[_source(revised_id, issue.paragraph_index, issue.paragraph_text)]))
    # 相同文字的样式改动也应出现在差异里，即便尚未违反规则。
    for old_index, new_index in aligned.items():
        old = old_paragraphs[old_index]
        new = new_paragraphs[new_index]
        fields = ("style_name", "alignment", "line_spacing", "space_before", "space_after", "first_line_indent_chars", "font")
        if any(getattr(old, field) != getattr(new, field) for field in fields):
            findings.append(Finding(category="格式变化", status="changed", message="段落样式已变化", sources=[_source(original_id, old_index, old.text), _source(revised_id, new_index, new.text)]))
    return VersionCompareResult(original_id=original_id, revised_id=revised_id, rule_id=rule_id, original_issue_count=len(old_issues), revised_issue_count=len(new_issues), findings=findings)


def _normalize(value: str, kind: str) -> str | None:
    cleaned = value.strip().replace("，", "").replace(",", "")
    if kind == "text":
        return re.sub(r"\s+", "", cleaned).casefold() or None
    if kind == "number":
        match = re.fullmatch(r"([+-]?\d+(?:\.\d+)?)\s*(元|千元|万元|亿元|%)?", cleaned)
        if not match:
            return None
        try:
            multiplier = {None: 1, "元": 1, "千元": 1000, "万元": 10000, "亿元": 100000000, "%": 1}[match.group(2)]
            unit = match.group(2)
            family = "percent" if unit == "%" else "money" if unit in {"元", "千元", "万元", "亿元"} else "scalar"
            normalized = Decimal(match.group(1)) * multiplier
            return f"{family}:{format(normalized.normalize(), 'f')}"
        except InvalidOperation:
            return None
    match = re.fullmatch(r"(\d{4})[年/.-](\d{1,2})[月/.-](\d{1,2})日?", cleaned)
    if not match:
        return None
    from datetime import date
    try:
        return date(*map(int, match.groups())).isoformat()
    except ValueError:
        return None


def _candidates(document_id: int, paragraphs: list[ContentParagraph], field: FieldSpec, page_map: list[int] | None) -> list[tuple[str, SourceRef]]:
    names = [field.name, *field.aliases]
    pattern = re.compile(r"(?:^|[\s，,；;])(?:" + "|".join(re.escape(name.strip()) for name in names if name.strip()) + r")\s*[：:]\s*(.{1,80}?)(?=$|[，,。；;])", re.I)
    matches: list[tuple[str, SourceRef]] = []
    for paragraph in paragraphs:
        for match in pattern.finditer(paragraph.text):
            value = match.group(1).strip()
            page = page_map[paragraph.index] if page_map and paragraph.index < len(page_map) else None
            matches.append((value, SourceRef(document_id=document_id, paragraph_index=paragraph.index, page_number=page, quote=match.group(0).strip())))
    return matches[:10]


def compare_fields(
    document_ids: list[int], baseline_id: int, fields: list[FieldSpec],
    contents: dict[int, list[ContentParagraph]], page_maps: dict[int, list[int] | None],
) -> CrossDocumentResult:
    results: list[CrossFieldResult] = []
    for field in fields:
        matches = {doc_id: _candidates(doc_id, contents[doc_id], field, page_maps.get(doc_id)) for doc_id in document_ids}
        baseline_matches = matches[baseline_id]
        baseline_normalized = _normalize(baseline_matches[0][0], field.value_type) if len(baseline_matches) == 1 else None
        values: list[FieldValue] = []
        for doc_id in document_ids:
            candidates = matches[doc_id]
            if not candidates:
                values.append(FieldValue(document_id=doc_id, status="missing"))
                continue
            if len(candidates) != 1:
                values.append(FieldValue(document_id=doc_id, status="ambiguous", candidates=[ref for _, ref in candidates]))
                continue
            raw, source = candidates[0]
            normalized = _normalize(raw, field.value_type)
            status = "baseline" if doc_id == baseline_id and normalized is not None else "ambiguous" if normalized is None or baseline_normalized is None else "match" if normalized == baseline_normalized else "different"
            values.append(FieldValue(document_id=doc_id, value=raw, normalized_value=normalized, source=source, status=status))
        results.append(CrossFieldResult(name=field.name, baseline_value=baseline_matches[0][0] if len(baseline_matches) == 1 else None, values=values))
    return CrossDocumentResult(baseline_id=baseline_id, fields=results)
