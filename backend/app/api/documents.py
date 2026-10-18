"""文档路由：上传、解析、列表、下载、删除。

上传走「原始二进制请求体」（不用 multipart），因此不依赖 python-multipart：
  POST /api/documents?workspace_id=1&filename=a.docx
  body: docx 原始字节
"""

from pathlib import Path
from urllib.parse import quote
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import FileResponse, Response
from sqlalchemy.orm import Session, load_only
from starlette.concurrency import run_in_threadpool
import uuid

from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import CheckResult, Document, User
from app.models.content_review import ContentReview
from app.models.template_audit import TemplateReview
from app.schemas.check import Violation
from app.schemas.content_review import ContentReviewResult
from app.schemas.document import DocumentDetail, DocumentOut, ParsedDocument
from app.schemas.revision import RevisedCopyCreate
from app.schemas.template_audit import TemplateReviewResult
from app.services.docx_parser import parse_docx
from app.services.storage import save_upload, read_upload, require_storage_quota
from app.services.document_content import preview_bytes
from app.services.pdf_content import extract_pdf, page_map_from_pdf
from app.services.revision_copy import (
    ContentReplacement,
    RepairError,
    build_revised_copy,
    is_repairable_format,
)

router = APIRouter(prefix="/documents", tags=["documents"])
logger = logging.getLogger(__name__)

ALLOWED_SUFFIXES = (".docx", ".pdf")


def _to_detail(doc: Document) -> DocumentDetail:
    parsed = None
    if doc.parsed_json and doc.file_type == "docx":
        parsed = ParsedDocument.model_validate(doc.parsed_json)
    return DocumentDetail(
        id=doc.id,
        workspace_id=doc.workspace_id,
        filename=doc.filename,
        size=doc.size,
        created_at=doc.created_at,
        parsed=parsed,
        file_type=doc.file_type,
        pdf_page_map=page_map_from_pdf(doc.pdf_json),
        pdf_ocr_pages=doc.pdf_json.get("ocr_pages", []) if doc.pdf_json else None,
    )


@router.post("", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    workspace_id: int,
    filename: str = "upload.docx",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentDetail:
    require_membership(db, user, workspace_id)
    if not filename.lower().endswith(ALLOWED_SUFFIXES):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 .docx 或 .pdf 文件")
    kind = "pdf" if filename.lower().endswith(".pdf") else "docx"
    content = await read_upload(request, kind)
    require_storage_quota(db, workspace_id, len(content))
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件为空")
    stored_path, _ = save_upload(content, filename)
    try:
        parsed = await run_in_threadpool(parse_docx, stored_path) if kind == "docx" else None
        pdf_data = await run_in_threadpool(extract_pdf, content) if kind == "pdf" else None
    except Exception as exc:  # noqa: BLE001 - 解析失败应提示用户而非 500
        Path(stored_path).unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"解析失败：{exc}"
        ) from exc

    doc = Document(
        workspace_id=workspace_id,
        filename=filename,
        stored_path=stored_path,
        size=len(content),
        parsed_json=parsed.model_dump() if parsed else None,
        pdf_json=pdf_data,
        created_by=user.id,
    )
    db.add(doc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        Path(stored_path).unlink(missing_ok=True)
        raise
    db.refresh(doc)
    return _to_detail(doc)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    workspace_id: int,
    before_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentOut]:
    require_membership(db, user, workspace_id)
    docs = (
        db.query(Document)
        .options(load_only(Document.id, Document.workspace_id, Document.filename, Document.size, Document.created_at, Document.pdf_json))
        .filter(Document.workspace_id == workspace_id)
        .filter(Document.id < before_id if before_id is not None else True)
        .order_by(Document.id.desc())
        .limit(limit)
        .all()
    )
    return [DocumentOut(id=d.id, workspace_id=d.workspace_id, filename=d.filename, size=d.size,
                        created_at=d.created_at, file_type=d.file_type,
                        pdf_page_map=page_map_from_pdf(d.pdf_json),
                        pdf_ocr_pages=d.pdf_json.get("ocr_pages", []) if d.pdf_json else None) for d in docs]


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentDetail:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    require_membership(db, user, doc.workspace_id)
    return _to_detail(doc)


@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    require_membership(db, user, doc.workspace_id)
    if not Path(doc.stored_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件已丢失")
    return FileResponse(doc.stored_path, filename=doc.filename)


@router.get("/{document_id}/preview")
def preview_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(404, "文档不存在")
    require_membership(db, user, doc.workspace_id)
    if not Path(doc.stored_path).is_file():
        raise HTTPException(404, "文档文件已丢失")
    try:
        content = preview_bytes(doc.stored_path) if doc.file_type == "docx" else Path(doc.stored_path).read_bytes()
    except Exception as exc:
        raise HTTPException(400, "无法生成文档预览") from exc
    return Response(
        content, media_type="application/pdf" if doc.file_type == "pdf" else "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/{document_id}/revised-copy")
def create_revised_copy(
    document_id: int,
    body: RevisedCopyCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    """按用户确认的审查项生成内存中的 .docx 副本，源文件保持不变。"""
    require_membership(db, user, body.workspace_id)
    doc = db.get(Document, document_id)
    if doc is None or doc.workspace_id != body.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    if doc.file_type != "docx":
        raise HTTPException(400, "PDF 暂不支持生成 Word 修订副本")
    if not Path(doc.stored_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档文件已丢失")

    format_violations: list[Violation] = []
    if body.format_violation_indexes:
        if body.check_id is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "请选择对应的格式审查结果")
        check = db.get(CheckResult, body.check_id)
        if check is None or check.workspace_id != body.workspace_id or check.document_id != doc.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "格式审查结果不存在")
        if len(set(body.format_violation_indexes)) != len(body.format_violation_indexes):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "格式修订项不能重复")
        for index in body.format_violation_indexes:
            if not 0 <= index < len(check.violations_json):
                raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "格式修订项不存在")
            violation = Violation.model_validate(check.violations_json[index])
            if not is_repairable_format(violation):
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST,
                    f"「{violation.message}」暂不支持自动修复",
                )
            format_violations.append(violation)

    content_fixes: list[ContentReplacement] = []
    seen_content_keys: set[tuple[int, int]] = set()
    for fix in body.content_fixes:
        key = (fix.review_id, fix.issue_index)
        if key in seen_content_keys:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "内容修订项不能重复")
        seen_content_keys.add(key)
        review = db.get(ContentReview, fix.review_id)
        if review is None or review.workspace_id != body.workspace_id or review.document_id != doc.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "内容审查记录不存在")
        result = ContentReviewResult.model_validate(review.result_json)
        if not 0 <= fix.issue_index < len(result.issues):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "内容修订项不存在")
        issue = result.issues[fix.issue_index]
        content_fixes.append(
            ContentReplacement(
                paragraph_index=issue.paragraph_index,
                quote=issue.quote,
                replacement_text=fix.replacement_text,
                category=issue.category,
            )
        )

    seen_template_keys: set[tuple[int, int]] = set()
    for fix in body.template_fixes:
        key = (fix.review_id, fix.issue_index)
        if key in seen_template_keys:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "模板修订项不能重复")
        seen_template_keys.add(key)
        review = db.get(TemplateReview, fix.review_id)
        if review is None or review.workspace_id != body.workspace_id or review.document_id != doc.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "表单模板审查记录不存在")
        result = TemplateReviewResult.model_validate(review.result_json)
        if not 0 <= fix.issue_index < len(result.issues):
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "模板修订项不存在")
        issue = result.issues[fix.issue_index]
        if not issue.repairable:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"「{issue.message}」暂不支持自动修订")
        if issue.format_violation is not None:
            if not is_repairable_format(issue.format_violation):
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"「{issue.message}」暂不支持自动修订")
            format_violations.append(issue.format_violation)
            continue
        replacement = (fix.replacement_text or "").strip()
        if not replacement:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "模板文字修订必须填写替换内容")
        if issue.document_content_index is None or not issue.quote:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "模板问题缺少可安全替换的原文")
        content_fixes.append(
            ContentReplacement(
                paragraph_index=issue.document_content_index,
                quote=issue.quote,
                replacement_text=replacement,
                category=f"表单模板审查·{issue.category}",
            )
        )

    try:
        content = build_revised_copy(
            doc.stored_path, doc.filename, format_violations, content_fixes
        )
    except RepairError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("生成修订后副本失败：document_id=%s", document_id)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "无法生成修订后副本") from exc

    filename = f"{Path(doc.filename).stem}_修订后副本.docx"
    return Response(
        content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Cache-Control": "no-store",
        },
    )


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    require_membership(db, user, doc.workspace_id)
    original = Path(doc.stored_path)
    staged = original.with_name(original.name + ".deleting-" + uuid.uuid4().hex)
    if original.is_file():
        original.replace(staged)
    db.query(CheckResult).filter(CheckResult.document_id == doc.id).delete(synchronize_session=False)
    db.query(ContentReview).filter(
        ContentReview.workspace_id == doc.workspace_id,
        ContentReview.document_id == doc.id,
    ).delete(synchronize_session=False)
    db.query(TemplateReview).filter(
        TemplateReview.workspace_id == doc.workspace_id,
        TemplateReview.document_id == doc.id,
    ).delete(synchronize_session=False)
    db.delete(doc)
    try:
        db.commit()
    except Exception:
        db.rollback()
        if staged.is_file():
            staged.replace(original)
        raise
    staged.unlink(missing_ok=True)
