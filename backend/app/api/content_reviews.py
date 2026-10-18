"""独立的内容审查接口，所有文档访问均校验工作区成员身份。"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, status, Query
from openai import APITimeoutError
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import Document, User
from app.models.content_review import ContentReview
from app.schemas.content_review import ContentReviewCreate, ContentReviewOut
from app.services.deepseek_content import review_content, review_content_chunked, validate_chunked
from app.services.document_content import read_content, validate_content
from app.services.pdf_content import paragraphs_from_pdf

router = APIRouter(prefix="/content-reviews", tags=["content-reviews"])


def _out(item: ContentReview) -> ContentReviewOut:
    return ContentReviewOut(
        id=item.id, workspace_id=item.workspace_id, document_id=item.document_id,
        instructions=item.instructions, model=item.model,
        paragraph_count=item.paragraph_count, created_at=item.created_at,
        **item.result_json,
    )


def _document(db: Session, workspace_id: int, document_id: int) -> Document:
    doc = db.get(Document, document_id)
    if doc is None or doc.workspace_id != workspace_id:
        raise HTTPException(404, "文档不存在")
    return doc


@router.post("", response_model=ContentReviewOut, status_code=201)
def create_review(
    body: ContentReviewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> ContentReviewOut:
    require_membership(db, user, body.workspace_id)
    doc = _document(db, body.workspace_id, body.document_id)
    source_path = doc.stored_path
    if not Path(doc.stored_path).is_file():
        raise HTTPException(404, "文档文件已丢失，请重新上传")
    try:
        paragraphs = paragraphs_from_pdf(doc.pdf_json or {}) if doc.file_type == "pdf" else read_content(doc.stored_path)
        (validate_chunked if body.chunked else validate_content)(paragraphs)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(400, "无法读取文档内容，请重新上传有效的 Word 或 PDF 文件") from exc
    if not settings.deepseek_api_key:
        raise HTTPException(503, "请在后端配置 DEEPSEEK_API_KEY 后使用内容审查")
    try:
        result = (review_content_chunked if body.chunked else review_content)(paragraphs, body.instructions)
    except APITimeoutError as exc:
        raise HTTPException(504, "DeepSeek 内容审查超时，请稍后重试") from exc
    except Exception as exc:
        # 不将 SDK 错误体、原文或配置泄露给前端。
        raise HTTPException(502, "DeepSeek 审查失败或返回无效的原文引用，请稍后重试") from exc
    # 审查期间文档可能已被其他会话删除；不能重新写入其历史。
    from sqlalchemy import select
    if db.scalar(select(Document.stored_path).where(Document.id == body.document_id, Document.workspace_id == body.workspace_id)) != source_path:
        raise HTTPException(404, "文档已删除，本次审查结果不再保存")
    item = ContentReview(
        workspace_id=body.workspace_id, document_id=doc.id,
        instructions=body.instructions, model=settings.deepseek_model,
        paragraph_count=len(paragraphs), result_json=result.model_dump(),
        created_by=user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _out(item)


@router.get("", response_model=list[ContentReviewOut])
def list_reviews(
    workspace_id: int, document_id: int,
    before_id: int | None = None, limit: int = Query(default=50, ge=1, le=100),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[ContentReviewOut]:
    require_membership(db, user, workspace_id)
    _document(db, workspace_id, document_id)
    items = db.query(ContentReview).filter(
        ContentReview.workspace_id == workspace_id,
        ContentReview.document_id == document_id,
    ).filter(ContentReview.id < before_id if before_id is not None else True).order_by(ContentReview.id.desc()).limit(limit).all()
    return [_out(item) for item in items]


@router.delete("/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_review(
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除一条内容审查记录，不改动源文档。"""
    item = db.get(ContentReview, review_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "内容审查记录不存在")
    require_membership(db, user, item.workspace_id)
    db.delete(item)
    db.commit()
