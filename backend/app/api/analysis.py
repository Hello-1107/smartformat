"""按需分析两版文档、文档结构及同一工作区的多份材料。"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import Document, Rule, User
from app.schemas.analysis import (
    CrossDocumentRequest, CrossDocumentResult, StructureCheckRequest,
    StructureCheckResult, VersionCompareRequest, VersionCompareResult,
)
from app.schemas.document import ParsedDocument, PARSER_VERSION
from app.schemas.rule import RuleSet
from app.services.document_analysis import check_structure, compare_fields, compare_versions
from app.services.document_content import read_content
from app.services.docx_parser import parse_docx
from app.services.pdf_content import page_map_from_pdf, paragraphs_from_pdf
from app.services.report_export import sign_analysis


router = APIRouter(prefix="/analysis", tags=["analysis"])


def _document(db: Session, workspace_id: int, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.workspace_id != workspace_id:
        raise HTTPException(404, f"文档 ID {document_id} 不存在")
    if not Path(doc.stored_path).is_file():
        raise HTTPException(404, f"文档「{doc.filename}」的文件已丢失")
    return doc


def _word_parsed(doc: Document) -> ParsedDocument:
    if doc.file_type != "docx":
        raise HTTPException(400, "此项审查仅支持 Word 文档")
    if doc.parsed_json is None or doc.parsed_json.get("parser_version") != PARSER_VERSION:
        doc.parsed_json = parse_docx(doc.stored_path).model_dump()
    return ParsedDocument.model_validate(doc.parsed_json)


@router.post("/versions", response_model=VersionCompareResult)
def version_compare(body: VersionCompareRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> VersionCompareResult:
    require_membership(db, user, body.workspace_id)
    original = _document(db, body.workspace_id, body.original_id)
    revised = _document(db, body.workspace_id, body.revised_id)
    rule = db.get(Rule, body.rule_id)
    if rule is None or rule.workspace_id != body.workspace_id:
        raise HTTPException(404, "格式规则不存在")
    try:
        result = compare_versions(original.id, revised.id, rule.id, _word_parsed(original), _word_parsed(revised), RuleSet.model_validate(rule.ruleset_json))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result.export_signature = sign_analysis("versions", body.workspace_id, result)
    return result


@router.post("/structure", response_model=StructureCheckResult)
def structure_check(body: StructureCheckRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> StructureCheckResult:
    require_membership(db, user, body.workspace_id)
    doc = _document(db, body.workspace_id, body.document_id)
    try:
        result = check_structure(doc.id, _word_parsed(doc), body.required_headings, body.require_order)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    result.export_signature = sign_analysis("structure", body.workspace_id, result)
    return result


@router.post("/cross-documents", response_model=CrossDocumentResult)
def cross_documents(body: CrossDocumentRequest, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> CrossDocumentResult:
    require_membership(db, user, body.workspace_id)
    docs = [_document(db, body.workspace_id, doc_id) for doc_id in body.document_ids]
    try:
        contents = {doc.id: paragraphs_from_pdf(doc.pdf_json or {}) if doc.file_type == "pdf" else read_content(doc.stored_path) for doc in docs}
    except Exception as exc:
        raise HTTPException(400, "无法读取核对材料，请检查文件") from exc
    maps = {doc.id: page_map_from_pdf(doc.pdf_json) for doc in docs}
    result = compare_fields(body.document_ids, body.baseline_id, body.fields, contents, maps)
    result.export_signature = sign_analysis("cross-documents", body.workspace_id, result)
    return result
