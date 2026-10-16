"""当前工作区文档模板的配置、版本与审查接口。"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import Response
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import Document, User
from app.models.template_audit import DocumentTemplate, TemplateReview
from app.schemas.template_audit import (
    DocumentTemplateOut,
    TemplateConfiguration,
    TemplateConfigurationUpdate,
    TemplateReviewCreate,
    TemplateReviewOut,
    TemplateReviewResult,
)
from app.services.document_content import preview_bytes
from app.services.storage import save_upload
from app.services.template_audit import extract_template_configuration, review_against_template

router = APIRouter(prefix="/template-audits", tags=["template-audits"])


def _template_out(item: DocumentTemplate) -> DocumentTemplateOut:
    return DocumentTemplateOut(
        id=item.id,
        workspace_id=item.workspace_id,
        version=item.version,
        name=item.name,
        filename=item.filename,
        size=item.size,
        is_active=item.is_active,
        is_published=item.is_published,
        config=TemplateConfiguration.model_validate(item.config_json),
        created_at=item.created_at,
    )


def _review_out(item: TemplateReview) -> TemplateReviewOut:
    result = TemplateReviewResult.model_validate(item.result_json)
    return TemplateReviewOut(
        id=item.id,
        workspace_id=item.workspace_id,
        template_id=item.template_id,
        template_version=item.template_version,
        document_id=item.document_id,
        created_at=item.created_at,
        **result.model_dump(),
    )


def _active(db: Session, workspace_id: int) -> DocumentTemplate | None:
    return (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.workspace_id == workspace_id, DocumentTemplate.is_active.is_(True))
        .order_by(DocumentTemplate.version.desc())
        .first()
    )


@router.get("/current", response_model=DocumentTemplateOut | None)
def get_current_template(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentTemplateOut | None:
    require_membership(db, user, workspace_id)
    item = _active(db, workspace_id)
    return _template_out(item) if item else None


@router.get("/versions", response_model=list[DocumentTemplateOut])
def list_template_versions(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentTemplateOut]:
    require_membership(db, user, workspace_id)
    items = (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.workspace_id == workspace_id)
        .order_by(DocumentTemplate.version.desc())
        .limit(20)
        .all()
    )
    return [_template_out(item) for item in items]


@router.post("/template", response_model=DocumentTemplateOut, status_code=status.HTTP_201_CREATED)
async def upload_template(
    request: Request,
    workspace_id: int,
    filename: str = "template.docx",
    name: str = "当前文档模板",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentTemplateOut:
    require_membership(db, user, workspace_id)
    if not filename.lower().endswith(".docx"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "模板仅支持 .docx 文件")
    if not name.strip():
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "模板名称不能为空")
    content = await request.body()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "模板文件为空")
    stored_path, _ = save_upload(content, filename)
    try:
        config = extract_template_configuration(stored_path)
    except Exception as exc:  # noqa: BLE001
        Path(stored_path).unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"模板解析失败：{exc}") from exc
    latest = (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.workspace_id == workspace_id)
        .order_by(DocumentTemplate.version.desc())
        .first()
    )
    db.query(DocumentTemplate).filter(
        DocumentTemplate.workspace_id == workspace_id,
        DocumentTemplate.is_active.is_(True),
    ).update({DocumentTemplate.is_active: False}, synchronize_session=False)
    item = DocumentTemplate(
        workspace_id=workspace_id,
        version=(latest.version + 1) if latest else 1,
        name=name.strip(),
        filename=filename,
        stored_path=stored_path,
        size=len(content),
        is_active=True,
        is_published=False,
        config_json=config.model_dump(),
        created_by=user.id,
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return _template_out(item)


@router.put("/current", response_model=DocumentTemplateOut)
def update_current_template(
    body: TemplateConfigurationUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentTemplateOut:
    require_membership(db, user, body.workspace_id)
    item = _active(db, body.workspace_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "当前工作区尚未上传模板")
    config = TemplateConfiguration.model_validate(item.config_json)
    existing = {block.id: block for block in config.blocks}
    if set(existing) != {block.id for block in body.blocks}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "模板区域与当前版本不一致，请刷新后重试")
    for update in body.blocks:
        block = existing[update.id]
        block.label = update.label.strip()
        block.mode = update.mode
        block.required = update.required
        block.data_type = update.data_type
        block.check_format = update.check_format
    config.check_page = body.check_page
    item.name = body.name.strip()
    item.config_json = config.model_dump()
    item.is_published = True
    db.commit()
    db.refresh(item)
    return _template_out(item)


@router.post("/versions/{template_id}/activate", response_model=DocumentTemplateOut)
def activate_template_version(
    template_id: int,
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentTemplateOut:
    require_membership(db, user, workspace_id)
    item = db.get(DocumentTemplate, template_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板版本不存在")
    if not Path(item.stored_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板文件已丢失")
    db.query(DocumentTemplate).filter(
        DocumentTemplate.workspace_id == workspace_id,
        DocumentTemplate.is_active.is_(True),
    ).update({DocumentTemplate.is_active: False}, synchronize_session=False)
    item.is_active = True
    db.commit()
    db.refresh(item)
    return _template_out(item)


@router.get("/templates/{template_id}/preview")
def preview_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> Response:
    item = db.get(DocumentTemplate, template_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板不存在")
    require_membership(db, user, item.workspace_id)
    if not Path(item.stored_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板文件已丢失")
    return Response(
        preview_bytes(item.stored_path, content_prefix="sf_template"),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Cache-Control": "no-store"},
    )


@router.post("/reviews", response_model=TemplateReviewOut, status_code=status.HTTP_201_CREATED)
def create_template_review(
    body: TemplateReviewCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> TemplateReviewOut:
    require_membership(db, user, body.workspace_id)
    template = _active(db, body.workspace_id)
    if template is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先上传并确认当前模板")
    if not template.is_published:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先在模板配置页确认区域用途并保存发布")
    document = db.get(Document, body.document_id)
    if document is None or document.workspace_id != body.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "待审文档不存在")
    if not Path(template.stored_path).is_file() or not Path(document.stored_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板或待审文档文件已丢失")
    config = TemplateConfiguration.model_validate(template.config_json)
    try:
        result = review_against_template(config, document.stored_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"模板审查失败：{exc}") from exc
    review = TemplateReview(
        workspace_id=body.workspace_id,
        template_id=template.id,
        template_version=template.version,
        document_id=document.id,
        result_json=result.model_dump(),
        created_by=user.id,
    )
    db.add(review)
    db.commit()
    db.refresh(review)
    return _review_out(review)


@router.get("/reviews", response_model=list[TemplateReviewOut])
def list_template_reviews(
    workspace_id: int,
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[TemplateReviewOut]:
    require_membership(db, user, workspace_id)
    document = db.get(Document, document_id)
    if document is None or document.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    items = (
        db.query(TemplateReview)
        .filter(TemplateReview.workspace_id == workspace_id, TemplateReview.document_id == document_id)
        .order_by(TemplateReview.created_at.desc(), TemplateReview.id.desc())
        .limit(50)
        .all()
    )
    return [_review_out(item) for item in items]


@router.delete("/reviews/{review_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template_review(
    review_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    item = db.get(TemplateReview, review_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板审查记录不存在")
    require_membership(db, user, item.workspace_id)
    db.delete(item)
    db.commit()
