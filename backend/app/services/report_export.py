"""把一条当前审查结果整理成可定位的 Word 报告，不重新审查或保存报告。"""

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from io import BytesIO
from typing import Literal

from docx import Document as WordDocument
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor

from app.config import settings
from app.models import Document
from app.models.check import CheckResult
from app.models.content_review import ContentReview
from app.models.template_audit import TemplateReview
from app.schemas.analysis import CrossDocumentResult, SourceRef, StructureCheckResult, VersionCompareResult
from app.schemas.check import CheckSummary, Violation
from app.schemas.content_review import ContentReviewResult
from app.schemas.template_audit import TemplateReviewResult
from app.services.document_content import content_locations
from app.services.pdf_content import page_map_from_pdf


AnalysisKind = Literal["versions", "structure", "cross-documents"]


@dataclass(frozen=True)
class ReportDocument:
    id: int
    filename: str
    file_type: str
    content_positions: dict[int, str] = field(default_factory=dict)
    pdf_pages: list[int] | None = None


@dataclass(frozen=True)
class ReportSource:
    filename: str
    location: str
    quote: str | None = None


@dataclass(frozen=True)
class ReportIssue:
    category: str
    status: str
    problem: str
    suggestion: str
    sources: list[ReportSource]
    expected: str | None = None
    actual: str | None = None


@dataclass(frozen=True)
class ReportData:
    review_type: str
    document_names: list[str]
    summary: str
    issues: list[ReportIssue]
    basis: str
    reviewed_at: datetime | None = None
    record_id: int | None = None
    note: str = ""


def report_document(doc: Document) -> ReportDocument:
    return ReportDocument(
        id=doc.id, filename=doc.filename, file_type=doc.file_type,
        content_positions=content_locations(doc.stored_path) if doc.file_type == "docx" else {},
        pdf_pages=page_map_from_pdf(doc.pdf_json),
    )


def _value(value: object) -> str:
    if value is None:
        return "未取得"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value)


def _position(doc: ReportDocument, index: int | None, *, kind: str, section: int | None = None, page: int | None = None) -> str:
    if doc.file_type == "pdf":
        number = page or (doc.pdf_pages[index] if index is not None and doc.pdf_pages and 0 <= index < len(doc.pdf_pages) else None)
        return f"第 {number} 页" if number else "原文位置待人工确认"
    if section is not None and index is None:
        return f"第 {section + 1} 个页面节"
    if index is None:
        return "无原文锚点，需人工确认"
    if kind == "format":
        return f"正文第 {index + 1} 段"
    return doc.content_positions.get(index, f"正文及表格内容段落第 {index + 1} 段")


def _source(doc: ReportDocument, index: int | None, quote: str | None, *, kind: str = "content", section: int | None = None, page: int | None = None) -> ReportSource:
    return ReportSource(doc.filename, _position(doc, index, kind=kind, section=section, page=page), quote)


def _format_suggestion(item: Violation) -> str:
    if item.severity == "unknown" or item.actual is None:
        return "该格式属性无法可靠解析，请对照规则和原文手工核实；核实前不视为合规。"
    if item.category in {"heading_structure", "coverage"}:
        return "对照审查说明与规则检查文档结构或覆盖范围，确认后手工调整。"
    return f"将对应格式属性调整为规则期望值：{_value(item.expected)}。修改后重新执行格式审查。"


def format_report(check: CheckResult, doc: ReportDocument) -> ReportData:
    summary = CheckSummary.model_validate(check.summary_json)
    issues: list[ReportIssue] = []
    for raw in check.violations_json:
        item = Violation.model_validate(raw)
        issues.append(ReportIssue(
            category=item.category, status="待核实" if item.severity == "unknown" else "需修改",
            problem=item.message, suggestion=_format_suggestion(item),
            sources=[_source(doc, item.paragraph_index, item.paragraph_text, kind="format", section=item.section_index)],
            expected=_value(item.expected), actual=_value(item.actual),
        ))
    snapshot = check.ruleset_snapshot or {}
    rule_name = (snapshot.get("ruleset") or {}).get("name") if isinstance(snapshot.get("ruleset"), dict) else None
    basis = f"格式规则：{rule_name or f'规则 ID {check.rule_id}'}"
    if snapshot.get("hash"):
        basis += f"；执行时快照 {str(snapshot['hash'])[:12]}"
    return ReportData("格式审查", [doc.filename],
                      f"本次记录包含 {len(issues)} 项格式发现，其中 {summary.unknown} 项无法判断。" if issues else "本次记录未发现格式问题。",
                      issues, basis, check.created_at, check.id,
                      "无法判断的项目需要人工核实，不能据此认定文档已通过格式审查。")


def content_report(review: ContentReview, doc: ReportDocument) -> ReportData:
    result = ContentReviewResult.model_validate(review.result_json)
    issues: list[ReportIssue] = []
    for item in result.issues:
        references = [_source(doc, item.paragraph_index, item.quote)]
        references.extend(_source(doc, ref.paragraph_index, ref.quote) for ref in item.related_references)
        suggestion = item.suggestion
        if item.recommended_replacement:
            suggestion += f"\n推荐替换文本：{item.recommended_replacement}"
        issues.append(ReportIssue(item.category, item.severity, item.reason, suggestion, references))
    note = "内容建议由 DeepSeek 生成，引用已按原文校验；事实、逻辑和修改方案仍需人工核实。"
    if doc.file_type == "pdf":
        note += " PDF 页码来自提取或 OCR 结果；扫描页文字可能识别错误，请对照原页。"
    return ReportData("内容审查", [doc.filename], result.summary, issues,
                      f"审查模型：{review.model}；非空段落：{review.paragraph_count}", review.created_at, review.id, note)


def _template_suggestion(category: str, expected: object, replacement: str | None) -> str:
    if replacement:
        return f"对照模板确认后，将引用文字修改为：{replacement}。"
    if category == "必填":
        return "核对原始资料，在对应必填区域补充真实内容；不要根据报告猜测填写值。"
    if category in {"结构", "表格"}:
        return "对照模板检查缺失或多出的区域，并人工确认结构映射后调整。"
    if category in {"格式", "页面", "固定内容"} and expected is not None:
        return f"对照模板将相应属性或固定内容调整为：{_value(expected)}。"
    return "对照模板与原始资料核实该字段，确认后手工修改。"


def template_report(review: TemplateReview, doc: ReportDocument) -> ReportData:
    result = TemplateReviewResult.model_validate(review.result_json)
    snapshot = review.result_json.get("template_snapshot") or {}
    blocks = (snapshot.get("config") or {}).get("blocks", []) if isinstance(snapshot, dict) else []
    template_positions = {block.get("id"): block.get("location") for block in blocks if isinstance(block, dict)}
    issues: list[ReportIssue] = []
    for item in result.issues:
        if item.document_content_index is not None:
            source = _source(doc, item.document_content_index, item.quote or (_value(item.actual) if item.actual is not None else None))
        elif item.format_violation and item.format_violation.paragraph_index is not None:
            source = _source(doc, item.format_violation.paragraph_index, item.quote, kind="format")
        elif item.format_violation and item.format_violation.scope == "page":
            source = ReportSource(doc.filename, "页面设置，具体页面节待人工确认")
        else:
            location = template_positions.get(item.template_block_id)
            source = ReportSource(doc.filename, f"待审文档未找到对应区域；模板位置：{location}" if location else "待审文档无可定位原文，需人工检查结构")
        issues.append(ReportIssue(
            item.category, item.severity, item.message,
            _template_suggestion(item.category, item.expected, item.recommended_replacement),
            [source], expected=_value(item.expected) if item.expected is not None else None,
            actual=_value(item.actual) if item.actual is not None else None,
        ))
    ai = result.ai_review
    if ai and ai.status == "completed":
        labels = {block.get("id"): block.get("label") for block in blocks if isinstance(block, dict)}
        for item in ai.suggestions:
            source = (_source(doc, item.document_content_index, item.quote)
                      if item.document_content_index is not None else
                      ReportSource(doc.filename, f"{labels.get(item.block_id) or template_positions.get(item.block_id) or '所选字段'}，需人工定位", item.quote))
            advice = item.suggestion + (f"；可核实的替换文字：{item.recommended_replacement}" if item.recommended_replacement else "")
            issues.append(ReportIssue("AI填写建议", "提示", item.reason, advice, [source], actual=item.quote))
    ai_note = (f"；DeepSeek 建议：{ai.status}（{ai.model or '未配置'}，选中 {len(ai.field_ids)} 个字段）" if ai else "；未启用 DeepSeek 建议")
    return ReportData("表单模板审查", [doc.filename], result.summary, issues,
                      f"模板版本：{review.template_version}" + ("；使用审查时配置快照" if snapshot else "；旧记录无配置快照") + ai_note,
                      review.created_at, review.id,
                      "缺失区域和页面级问题没有精确段落锚点，报告会标明模板位置或要求人工定位。AI 建议不改变合规结论，也不会自动修改原文。")


def _analysis_source(ref: SourceRef, docs: dict[int, ReportDocument], kind: str) -> ReportSource:
    doc = docs[ref.document_id]
    return _source(doc, ref.paragraph_index, ref.quote, kind=kind, page=ref.page_number)


def _analysis_suggestion(status: str, category: str) -> str:
    if status == "resolved":
        return "该问题在修改稿中已解决，无需继续修改；可人工确认对应改动。"
    if status == "uncertain" or status == "ambiguous":
        return "源段落或候选值无法可靠对应，请对照相关文件人工确认后再修改。"
    if status == "out_of_order":
        return "按配置的章节顺序调整标题，并复查正文引用。"
    if status == "missing" and category == "章节":
        return "核对章节要求并补齐缺失标题与相应正文内容；不得仅为通过检查添加空标题。"
    if status == "missing" and category == "图表":
        return "核对图表及正文引用，补齐对应题注或修正引用编号。"
    if status in {"duplicate", "gap"}:
        return "核对图表题注编号，按实际顺序修正并同步检查正文引用。"
    if category == "格式复审":
        return "按所选格式规则修正该位置，并再次运行格式审查。"
    return "核对所列原文与变化是否符合预期，必要时手工修改。"


def analysis_report(kind: AnalysisKind, result: VersionCompareResult | StructureCheckResult | CrossDocumentResult,
                    docs: dict[int, ReportDocument]) -> ReportData:
    if kind == "cross-documents":
        assert isinstance(result, CrossDocumentResult)
        issues: list[ReportIssue] = []
        for field in result.fields:
            baseline = next((value for value in field.values if value.document_id == result.baseline_id), None)
            for item in field.values:
                if item.status in {"baseline", "match"}:
                    continue
                doc = docs[item.document_id]
                sources = [_analysis_source(item.source, docs, "content")] if item.source else []
                sources.extend(_analysis_source(ref, docs, "content") for ref in item.candidates)
                if not sources:
                    sources = [ReportSource(doc.filename, f"未找到字段「{field.name}」，无原文锚点")]
                if baseline and baseline.source:
                    sources.append(_analysis_source(baseline.source, docs, "content"))
                problem = {"different": "与基准值不一致", "missing": "未找到字段", "ambiguous": "找到多个候选值或无法可靠比较"}[item.status]
                suggestion = (f"核对本文件与基准文档「{docs[result.baseline_id].filename}」中字段「{field.name}」的原始依据，确认后更正。"
                              if item.status == "different" else "核对字段标签及原始资料，人工确认正确值；不要自动采用任一候选。")
                issues.append(ReportIssue(f"跨文档字段 {field.name}", item.status, problem, suggestion, sources,
                                          expected=field.baseline_value, actual=item.value))
        return ReportData("跨文档数据核对", [doc.filename for doc in docs.values()],
                          f"以「{docs[result.baseline_id].filename}」为基准；{len(issues)} 个字段结果需要核对。", issues,
                          "字段名、别名和基准由用户配置；系统不推断缺失事实。", note="一致项未列为待修改问题；候选值需要人工确认。")
    if kind == "versions":
        assert isinstance(result, VersionCompareResult)
        title = "版本对比与复审"
        names = [docs[result.original_id].filename, docs[result.revised_id].filename]
        summary = f"原稿 {result.original_issue_count} 项格式问题；修改稿 {result.revised_issue_count} 项。"
        basis = f"同一格式规则 ID {result.rule_id}"
        findings = result.findings
    else:
        assert isinstance(result, StructureCheckResult)
        title = "章节与图表完整性"
        names = [docs[result.document_id].filename]
        summary = f"章节与图表检查发现 {len(result.findings)} 项需处理或核实。"
        basis = "必需章节按文档文字出现与否检查，不要求标题格式；顺序按首次出现位置判断，图表按编号及引用规则检查。"
        findings = result.findings
    issues = [ReportIssue(item.category, item.status, item.message,
                          _analysis_suggestion(item.status, item.category),
                          [_analysis_source(ref, docs, "format") for ref in item.sources] or
                          [ReportSource(names[-1], "无原文锚点，需人工定位")]) for item in findings]
    return ReportData(title, names, summary, issues, basis,
                      note="已解决、文字变化等信息仅供核对；待确认项不能视为已经修复。" if kind == "versions" else
                           "缺失章节等问题不存在对应原文位置，需参考相邻章节人工定位。")


def _canonical(kind: AnalysisKind, workspace_id: int, result: VersionCompareResult | StructureCheckResult | CrossDocumentResult) -> bytes:
    data = {"kind": kind, "workspace_id": workspace_id,
            "result": result.model_dump(mode="json", exclude={"export_signature"})}
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sign_analysis(kind: AnalysisKind, workspace_id: int,
                  result: VersionCompareResult | StructureCheckResult | CrossDocumentResult) -> str:
    return hmac.new(settings.secret_key.encode("utf-8"), _canonical(kind, workspace_id, result), hashlib.sha256).hexdigest()


def verify_analysis(kind: AnalysisKind, workspace_id: int,
                    result: VersionCompareResult | StructureCheckResult | CrossDocumentResult) -> bool:
    return bool(result.export_signature) and hmac.compare_digest(result.export_signature, sign_analysis(kind, workspace_id, result))


def _safe(value: str) -> str:
    return re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", value)


def _set_font(style: object, size: float, bold: bool = False) -> None:
    style.font.name = "Microsoft YaHei"
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.color.rgb = RGBColor(0, 0, 0)
    rpr = style.element.get_or_add_rPr()
    fonts = rpr.rFonts
    if fonts is None:
        from docx.oxml import OxmlElement
        fonts = OxmlElement("w:rFonts")
        rpr.insert(0, fonts)
    fonts.set(qn("w:eastAsia"), "Microsoft YaHei")


def _line(doc: object, label: str, value: str) -> None:
    paragraph = doc.add_paragraph()
    paragraph.add_run(label).bold = True
    paragraph.add_run(_safe(value))


def render_report(data: ReportData) -> bytes:
    """只在内存中生成 DOCX，不改变源文档，也不保存导出历史。"""
    document = WordDocument()
    section = document.sections[0]
    section.page_width, section.page_height = Inches(8.5), Inches(11)
    section.top_margin = section.bottom_margin = Inches(0.82)
    section.left_margin = section.right_margin = Inches(0.86)
    styles = document.styles
    for name, size, bold in (("Normal", 10.5, False), ("Title", 18, True), ("Heading 1", 13, True), ("Heading 2", 11, True)):
        _set_font(styles[name], size, bold)
    styles["Normal"].paragraph_format.space_after = Pt(3)
    styles["Normal"].paragraph_format.line_spacing = 1.18
    styles["Heading 1"].paragraph_format.space_before = Pt(12)
    styles["Heading 1"].paragraph_format.space_after = Pt(5)
    styles["Heading 2"].paragraph_format.space_before = Pt(9)
    styles["Heading 2"].paragraph_format.space_after = Pt(4)
    document.add_paragraph("文档审查报告", style="Title")
    intro = document.add_paragraph(_safe(f"本报告记录「{data.review_type}」的当前审查结果，列出对应文件、原文位置、发现的问题及修改建议。"))
    intro.paragraph_format.space_after = Pt(12)
    _line(document, "审查类型  ", data.review_type)
    _line(document, "涉及文件  ", "；".join(data.document_names))
    if data.record_id is not None:
        _line(document, "审查记录  ", str(data.record_id))
    if data.reviewed_at is not None:
        reviewed = data.reviewed_at.replace(tzinfo=timezone.utc) if data.reviewed_at.tzinfo is None else data.reviewed_at
        _line(document, "审查时间  ", reviewed.astimezone().strftime("%Y-%m-%d %H:%M"))
    _line(document, "导出时间  ", datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M"))
    document.add_heading("审查概览", level=1)
    document.add_paragraph(_safe(data.summary))
    _line(document, "审查依据  ", data.basis)
    if data.note:
        document.add_paragraph(_safe(data.note))
    document.add_heading("问题与修改建议", level=1)
    if not data.issues:
        document.add_paragraph("本次结果没有需要列出的具体问题。")
    for number, item in enumerate(data.issues, 1):
        heading = document.add_heading(_safe(f"问题 {number} {item.category} {item.status}"), level=2)
        heading.paragraph_format.keep_with_next = True
        for source in item.sources:
            _line(document, "文件及位置  ", f"{source.filename}  {source.location}")
            if source.quote:
                _line(document, "原文引用  ", source.quote)
        _line(document, "问题说明  ", item.problem)
        if item.expected is not None:
            _line(document, "期望或基准  ", item.expected)
        if item.actual is not None:
            _line(document, "实际或候选  ", item.actual)
        _line(document, "修改建议  ", item.suggestion)
    document.core_properties.title = "文档审查报告"
    document.core_properties.subject = data.review_type
    document.core_properties.author = "SmartFormat"
    output = BytesIO()
    document.save(output)
    return output.getvalue()
