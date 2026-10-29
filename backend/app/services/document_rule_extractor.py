"""提取完整候选样式；存在冲突时必须由用户选择，不合成属性众数。"""

from pathlib import Path
import hashlib
import json
import re

from pydantic import BaseModel, Field

from app.schemas.document import ParsedParagraph, FontInfo
from app.schemas.rule import (
    FontRule, ParagraphRule, PageRule, RuleSet, ScopeRule,
    HeadingStructureRule, TemplateRegionRule,
)
from app.services.docx_parser import parse_docx


class StyleCandidate(BaseModel):
    id: str
    scope: str
    count: int
    examples: list[str]
    paragraph_indexes: list[int]
    style: ScopeRule


class TemplateExtraction(BaseModel):
    ruleset: RuleSet
    candidates: dict[str, list[StyleCandidate]]
    regions: list[TemplateRegionRule] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


def _scope(paragraph: ParsedParagraph, font: FontInfo | None = None) -> ScopeRule:
    return ScopeRule(
        font=FontRule.model_validate((font or paragraph.font).model_dump()),
        paragraph=ParagraphRule(**{key: getattr(paragraph, key) for key in ParagraphRule.model_fields}),
    )


_CAPTION = re.compile(r"^\s*(?:图|表)\s*[0-9一二三四五六七八九十]+(?:[-—.．][0-9]+)*")
_CODE_HINT = re.compile(r"(?:[{};]|=>|==|!=|\b(?:class|public|private|function|const|let|var|import|return)\b)")


def _is_prose(paragraph: ParsedParagraph) -> bool:
    """只从自然语言正文归纳章节样式，避免代码、图题和表题污染规则。"""
    text = paragraph.text.strip()
    if paragraph.level is not None or paragraph.is_title or len(text) < 8 or _CAPTION.match(text):
        return False
    if _CODE_HINT.search(text) and sum(text.count(char) for char in "{};()=") >= 3:
        return False
    compact = re.sub(r"\s+", "", text)
    if not compact:
        return False
    cjk = len(re.findall(r"[\u3400-\u9fff]", compact))
    letters = len(re.findall(r"[A-Za-z]", compact))
    return cjk / len(compact) >= 0.12 or (letters / len(compact) >= 0.65 and not _CODE_HINT.search(text))


def _dominant_body_style(paragraphs: list[ParsedParagraph]) -> ScopeRule | None:
    groups: dict[str, tuple[int, ScopeRule]] = {}
    for paragraph in paragraphs:
        if not _is_prose(paragraph):
            continue
        style = _scope(paragraph)
        signature = json.dumps(style.model_dump(exclude_none=True), sort_keys=True, ensure_ascii=False)
        count, _ = groups.get(signature, (0, style))
        groups[signature] = (count + 1, style)
    return max(groups.values(), key=lambda item: item[0])[1] if groups else None


def _extract_regions(parsed) -> list[TemplateRegionRule]:
    anchors = [
        paragraph for paragraph in parsed.paragraphs
        if paragraph.text.strip() and (paragraph.is_title or paragraph.level is not None)
    ]
    regions: list[TemplateRegionRule] = []
    for position, paragraph in enumerate(anchors[:300]):
        end = anchors[position + 1].index if position + 1 < len(anchors) else len(parsed.paragraphs)
        body_style = None if paragraph.is_title else _dominant_body_style(parsed.paragraphs[paragraph.index + 1:end])
        anchor = re.sub(r"\s+", " ", paragraph.text).strip()
        region_id = hashlib.sha256(f"{paragraph.index}:{anchor}".encode()).hexdigest()[:20]
        regions.append(TemplateRegionRule(
            id=region_id,
            label=anchor[:200],
            anchor=anchor[:500],
            level=0 if paragraph.is_title else int(paragraph.level or 0),
            mode="fixed",
            required=True,
            check_format=True,
            template_paragraph_index=paragraph.index,
            heading_style=_scope(paragraph),
            body_style=body_style,
        ))
    return regions


def extract_candidates(path: str | Path, name: str | None = None, filename: str | None = None) -> TemplateExtraction:
    parsed = parse_docx(path)
    original_name = Path(filename or parsed.filename).name
    groups: dict[str, dict[str, StyleCandidate]] = {}
    for paragraph in parsed.paragraphs:
        if not paragraph.text.strip():
            continue
        scope = "title" if paragraph.is_title else f"h{paragraph.level}" if paragraph.level else "body"
        group = groups.setdefault(scope, {})
        styles = [_scope(paragraph, run.font) for run in paragraph.runs] or [_scope(paragraph)]
        seen = set()
        for style in styles:
            signature = json.dumps(style.model_dump(exclude_none=True), sort_keys=True, ensure_ascii=False)
            if signature in seen:
                continue
            seen.add(signature)
            if signature not in group:
                group[signature] = StyleCandidate(
                    id=hashlib.sha256((scope + signature).encode()).hexdigest()[:20],
                    scope=scope, count=0, examples=[], paragraph_indexes=[], style=style,
                )
            candidate = group[signature]
            candidate.count += 1
            candidate.paragraph_indexes.append(paragraph.index)
            if len(candidate.examples) < 3:
                candidate.examples.append(paragraph.text[:160])
    if not groups:
        raise ValueError("文本模板没有可用于提取格式的正文或标题")
    page = PageRule.model_validate(parsed.sections[0].model_dump(exclude={"index"})) if parsed.sections else None
    regions = _extract_regions(parsed)
    ruleset = RuleSet(name=(name or Path(original_name).stem).strip()[:200],
                      description=f"从文本模板《{original_name}》提取；请确认章节区域和检查方式后创建规则。", page=page)
    headings = [p for p in parsed.paragraphs if p.level is not None and not p.is_title and p.text.strip()]
    if headings:
        ruleset.heading_structure = HeadingStructureRule(max_level=max(p.level for p in headings),
            require_numbered=all(p.numbered or p.text.lstrip()[:1].isdigit() for p in headings))
    candidates = {scope: list(group.values()) for scope, group in groups.items()}
    warnings = []
    if len(regions) >= 300:
        warnings.append("模板标题区域超过 300 个，仅载入前 300 个，请精简模板后复核。")
    if not regions:
        warnings.append("未识别到语义标题，将继续使用传统样式候选方式创建规则。")
    if len({json.dumps(s.model_dump(exclude={"index"}), sort_keys=True) for s in parsed.sections}) > 1:
        warnings.append("模板包含不同页面设置的多个节，请在编辑器确认适用于待审文件的页面规则。")
    return TemplateExtraction(ruleset=ruleset, candidates=candidates, regions=regions, warnings=warnings)


def extract_ruleset_from_document(path: str | Path, name: str | None = None, filename: str | None = None) -> RuleSet:
    """兼容单一样式提取；多候选时明确拒绝自动决定。"""
    extraction = extract_candidates(path, name, filename)
    ruleset = extraction.ruleset
    for scope, candidates in extraction.candidates.items():
        if len(candidates) != 1:
            raise ValueError(f"{scope} 存在多种候选样式，请先确认候选样式")
        if scope in {"title", "body"}:
            setattr(ruleset, scope, candidates[0].style)
        else:
            if ruleset.headings is None:
                ruleset.headings = {}
            ruleset.headings[scope] = candidates[0].style
    return ruleset
