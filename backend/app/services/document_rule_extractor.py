"""提取完整候选样式；存在冲突时必须由用户选择，不合成属性众数。"""

from pathlib import Path
import hashlib
import json

from pydantic import BaseModel, Field

from app.schemas.document import ParsedParagraph, FontInfo
from app.schemas.rule import FontRule, ParagraphRule, PageRule, RuleSet, ScopeRule, HeadingStructureRule
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
    warnings: list[str] = Field(default_factory=list)


def _scope(paragraph: ParsedParagraph, font: FontInfo | None = None) -> ScopeRule:
    return ScopeRule(
        font=FontRule.model_validate((font or paragraph.font).model_dump()),
        paragraph=ParagraphRule(**{key: getattr(paragraph, key) for key in ParagraphRule.model_fields}),
    )


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
    ruleset = RuleSet(name=(name or Path(original_name).stem).strip()[:200],
                      description=f"从文本模板《{original_name}》提取；请确认候选样式后创建规则。", page=page)
    headings = [p for p in parsed.paragraphs if p.level is not None and not p.is_title and p.text.strip()]
    if headings:
        ruleset.heading_structure = HeadingStructureRule(max_level=max(p.level for p in headings),
            require_numbered=all(p.numbered or p.text.lstrip()[:1].isdigit() for p in headings))
    candidates = {scope: list(group.values()) for scope, group in groups.items()}
    warnings = []
    if len({json.dumps(s.model_dump(exclude={"index"}), sort_keys=True) for s in parsed.sections}) > 1:
        warnings.append("模板包含不同页面设置的多个节，请在编辑器确认适用于待审文件的页面规则。")
    return TemplateExtraction(ruleset=ruleset, candidates=candidates, warnings=warnings)


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
