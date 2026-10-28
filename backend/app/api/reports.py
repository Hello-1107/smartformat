"""按当前单条审查结果导出 DOCX；不创建服务端报告历史。"""

import json
from pathlib import Path
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import CheckResult, Document, User
from app.models.content_review import ContentReview
from app.models.template_audit import TemplateReview
from app.schemas.analysis import CrossDocumentResult, StructureCheckResult, VersionCompareResult
from app.services.report_export import (
    AnalysisKind, analysis_report, content_report, format_report, render_report,
    report_document, template_report, verify_analysis,
)


router = APIRouter(prefix="/reports", tags=["reports"])
MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


class AnalysisExportBody(BaseModel):
    workspace_id: int
    result: dict[str, Any]


def _doc(db: Session, workspace_id: int, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.workspace_id != workspace_id:
        raise HTTPException(404, "文档或审查结果不存在")
    if not Path(doc.stored_path).is_file():
        raise HTTPException(404, "源文档已丢失，无法核对报告位置")
    return doc


def _download(content: bytes, filename: str) -> Response:
    return Response(
        content, media_type=MEDIA_TYPE,
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
            "X-Content-Type-Options": "nosniff",
        },
    )


@router.get("/checks/{check_id}")
def export_format_report(check_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    check = db.get(CheckResult, check_id)
    if check is None:
        raise HTTPException(404, "审查结果不存在")
    require_membership(db, user, check.workspace_id)
    doc = _doc(db, check.workspace_id, check.document_id)
    report = format_report(check, report_document(doc))
    return _download(render_report(report), f"{Path(doc.filename).stem}_格式审查报告.docx")


@router.get("/content-reviews/{review_id}")
def export_content_report(review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    review = db.get(ContentReview, review_id)
    if review is None:
        raise HTTPException(404, "审查结果不存在")
    require_membership(db, user, review.workspace_id)
    doc = _doc(db, review.workspace_id, review.document_id)
    report = content_report(review, report_document(doc))
    return _download(render_report(report), f"{Path(doc.filename).stem}_内容审查报告.docx")


@router.get("/template-reviews/{review_id}")
def export_template_report(review_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    review = db.get(TemplateReview, review_id)
    if review is None:
        raise HTTPException(404, "审查结果不存在")
    require_membership(db, user, review.workspace_id)
    doc = _doc(db, review.workspace_id, review.document_id)
    report = template_report(review, report_document(doc))
    return _download(render_report(report), f"{Path(doc.filename).stem}_表单模板审查报告.docx")


@router.post("/analysis/{kind}")
def export_analysis_report(kind: AnalysisKind, body: AnalysisExportBody,
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> Response:
    require_membership(db, user, body.workspace_id)
    if len(json.dumps(body.result, ensure_ascii=False)) > 300_000:
        raise HTTPException(413, "当前分析结果过大，无法导出")
    model = {"versions": VersionCompareResult, "structure": StructureCheckResult,
             "cross-documents": CrossDocumentResult}[kind]
    result = model.model_validate(body.result)
    if not verify_analysis(kind, body.workspace_id, result):
        raise HTTPException(400, "分析结果已变化或签名无效，请重新执行审查")
    if kind == "versions":
        document_ids = {result.original_id, result.revised_id}
        document_ids.update(ref.document_id for item in result.findings for ref in item.sources)
    elif kind == "structure":
        document_ids = {result.document_id}
        document_ids.update(ref.document_id for item in result.findings for ref in item.sources)
    else:
        document_ids = {result.baseline_id}
        document_ids.update(item.document_id for field in result.fields for item in field.values)
        document_ids.update(ref.document_id for field in result.fields for item in field.values
                            for ref in ([item.source] if item.source else []) + item.candidates)
    docs = {doc_id: report_document(_doc(db, body.workspace_id, doc_id)) for doc_id in sorted(document_ids)}
    report = analysis_report(kind, result, docs)
    filename = {"versions": "版本对比与复审报告.docx", "structure": "章节与图表完整性报告.docx",
                "cross-documents": "跨文档数据核对报告.docx"}[kind]
    return _download(render_report(report), filename)
