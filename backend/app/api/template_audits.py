"""当前工作区文档模板的配置、版本与审查接口。"""

from pathlib import Path
import logging

from fastapi import APIRouter, Depends, HTTPException, Request, status, Query
from fastapi.responses import Response
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool

from app.database import get_db
from app.config import settings
from app.deps import get_current_user, require_membership
from app.models import Document, User, Workspace
from app.models.template_audit import DocumentTemplate, TemplateReview
from app.schemas.template_audit import (
    DocumentTemplateOut,
    TemplateConfiguration,
    TemplateConfigurationUpdate,
    TemplateRequirementDraftRequest,
    TemplateRequirementDraftResult,
    TemplateReviewCreate,
    TemplateReviewOut,
    TemplateReviewResult,
    TemplateAiReview,
)
from app.services.deepseek_template_content import review_template_fields
from app.services.document_content import preview_bytes
from app.services.storage import save_upload, read_upload, require_storage_quota
from app.services.deletion import discard_uploads, restore_uploads, stage_uploads
from app.services.template_audit import draft_field_requirements, extract_template_configuration, review_against_template

router = APIRouter(prefix="/template-audits", tags=["template-audits"])
logger = logging.getLogger(__name__)


@router.post("/requirements/draft", response_model=TemplateRequirementDraftResult)
def draft_requirements(body: TemplateRequirementDraftRequest, user: User = Depends(get_current_user)) -> TemplateRequirementDraftResult:
    # 仅解析用户填写的要求文字；不上传或读取模板中的个人信息。
    return draft_field_requirements(body.text)


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
        is_review_active=item.is_review_active,
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
        template_snapshot=item.result_json.get("template_snapshot"),
        **result.model_dump(),
    )


def _active(db: Session, workspace_id: int) -> DocumentTemplate | None:
    return (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.workspace_id == workspace_id, DocumentTemplate.is_active.is_(True))
        .order_by(DocumentTemplate.version.desc())
        .first()
    )


def _next_version(db: Session, workspace_id: int) -> int:
    workspace = db.query(Workspace).filter(Workspace.id == workspace_id).with_for_update().one()
    version = workspace.next_template_version
    workspace.next_template_version = version + 1
    return version


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
    before_id: int | None = None,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentTemplateOut]:
    require_membership(db, user, workspace_id)
    items = (
        db.query(DocumentTemplate)
        .filter(DocumentTemplate.workspace_id == workspace_id)
        .filter(DocumentTemplate.id < before_id if before_id is not None else True)
        .order_by(DocumentTemplate.id.desc())
        .limit(limit)
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
    content = await read_upload(request)
    require_storage_quota(db, workspace_id, len(content))
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "模板文件为空")
    stored_path, _ = save_upload(content, filename)
    try:
        config = await run_in_threadpool(extract_template_configuration, stored_path)
    except Exception as exc:  # noqa: BLE001
        Path(stored_path).unlink(missing_ok=True)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"模板解析失败：{exc}") from exc
    db.query(DocumentTemplate).filter(
        DocumentTemplate.workspace_id == workspace_id,
        DocumentTemplate.is_active.is_(True),
    ).update({DocumentTemplate.is_active: False}, synchronize_session="fetch")
    item = DocumentTemplate(
        workspace_id=workspace_id,
        version=_next_version(db, workspace_id),
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
    try:
        db.commit()
    except Exception:
        db.rollback()
        Path(stored_path).unlink(missing_ok=True)
        raise
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
    if body.template_id is not None and body.template_id != item.id:
        raise HTTPException(409, "当前模板已变化，请刷新后再保存")
    config = TemplateConfiguration.model_validate(item.config_json)
    existing = {block.id: block for block in config.blocks}
    if set(existing) != {block.id for block in body.blocks}:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "模板区域与当前版本不一致，请刷新后重试")
    for update in body.blocks:
        block = existing[update.id]
        changed_identity = block.label != update.label.strip() or block.mode != update.mode
        if block.recognition_confidence == "low" and not changed_identity and not update.recognition_confirmed:
            raise HTTPException(422, f"请先核对低置信度字段：{block.location}")
        if changed_identity or update.recognition_confirmed:
            block.recognition_confidence = "high"
            block.recognition_note = "用户已确认字段名称和区域用途"
            block.recognition_confirmed = True
        block.label = update.label.strip()
        block.mode = update.mode
        block.required = update.required
        block.data_type = update.data_type
        block.check_format = update.check_format
        if update.rules is not None:
            block.rules = update.rules
        block.requirement_text = update.requirement_text.strip()
        block.unsupported_requirements = update.unsupported_requirements
    for block in config.blocks:
        if (block.rules or block.requirement_text or block.unsupported_requirements) and block.mode != "variable":
            raise HTTPException(422, f"{block.label or block.location}不是可变字段，不能设置填写要求")
        for rule in block.rules:
            if rule.kind == "same_as" and (rule.other_block_id == block.id or
                                          rule.other_block_id not in existing or
                                          existing[rule.other_block_id].mode != "variable"):
                raise HTTPException(422, f"{block.label or block.location}的一致性规则引用了无效字段")
    if item.is_published:
        item = _new_draft(db, item)
    config.check_page = body.check_page
    item.name = body.name.strip()
    item.config_json = config.model_dump()
    item.is_published = True
    db.query(DocumentTemplate).filter(DocumentTemplate.workspace_id == body.workspace_id).update({DocumentTemplate.is_review_active: False}, synchronize_session="fetch")
    item.is_review_active = True
    db.commit()
    db.refresh(item)
    return _template_out(item)


@router.post("/current/reanalyze", response_model=DocumentTemplateOut)
def reanalyze_current_template(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentTemplateOut:
    """使用最新确定性识别逻辑重建配置，模板文件和版本号保持不变。"""
    require_membership(db, user, workspace_id)
    item = _active(db, workspace_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "当前工作区尚未上传表单模板")
    if not Path(item.stored_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板文件已丢失")
    previous = TemplateConfiguration.model_validate(item.config_json)
    try:
        config = extract_template_configuration(item.stored_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"重新识别模板失败：{exc}") from exc
    config.check_page = previous.check_page
    previous_blocks = {block.id: block for block in previous.blocks}
    for block in config.blocks:
        old = previous_blocks.get(block.id)
        if old and (old.rules or old.requirement_text or old.unsupported_requirements) and block.mode == "variable":
            block.rules = old.rules
            block.requirement_text = old.requirement_text
            block.unsupported_requirements = old.unsupported_requirements
            block.recognition_confidence = "low"
            block.recognition_note = "沿用上一版本填写要求，请核对字段映射"
    if item.is_published:
        item = _new_draft(db, item)
    item.config_json = config.model_dump()
    # 新识别结果必须由用户复核后重新发布，不能静默改变正在使用的审查规则。
    item.is_published = False
    db.commit()
    db.refresh(item)
    return _template_out(item)


def _new_draft(db: Session, source: DocumentTemplate) -> DocumentTemplate:
    source.is_active = False
    item = DocumentTemplate(workspace_id=source.workspace_id, version=_next_version(db, source.workspace_id),
        name=source.name, filename=source.filename, stored_path=source.stored_path, size=source.size,
        is_active=True, is_published=False, config_json=source.config_json, created_by=source.created_by)
    db.add(item)
    return item


@router.get("/templates/{template_id}", response_model=DocumentTemplateOut)
def get_template(template_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> DocumentTemplateOut:
    item = db.get(DocumentTemplate, template_id)
    if item is None:
        raise HTTPException(404, "模板不存在")
    require_membership(db, user, item.workspace_id)
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
    ).update({DocumentTemplate.is_active: False}, synchronize_session="fetch")
    item.is_active = True
    if item.is_published:
        db.query(DocumentTemplate).filter(DocumentTemplate.workspace_id == workspace_id).update({DocumentTemplate.is_review_active: False}, synchronize_session="fetch")
        item.is_review_active = True
    db.commit()
    db.refresh(item)
    return _template_out(item)


@router.delete("/versions/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template_version(
    template_id: int,
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    require_membership(db, user, workspace_id)
    item = db.get(DocumentTemplate, template_id)
    if item is None or item.workspace_id != workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板版本不存在")

    path = item.stored_path
    referenced_elsewhere = (
        db.query(DocumentTemplate.id).filter(DocumentTemplate.id != item.id, DocumentTemplate.stored_path == path).first()
        or db.query(Document.id).filter(Document.stored_path == path).first()
    )
    staged = stage_uploads({path} if not referenced_elsewhere else set())
    was_active, was_review_active = item.is_active, item.is_review_active
    try:
        # 历史审查报告引用版本号与配置快照；随该版本一并删除，避免悬空记录。
        db.query(TemplateReview).filter(TemplateReview.template_id == item.id).delete(synchronize_session=False)
        db.delete(item)
        db.flush()
        if was_active:
            replacement = db.query(DocumentTemplate).filter(DocumentTemplate.workspace_id == workspace_id).order_by(DocumentTemplate.version.desc()).first()
            if replacement is not None:
                replacement.is_active = True
        if was_review_active:
            replacement = (db.query(DocumentTemplate)
                           .filter(DocumentTemplate.workspace_id == workspace_id, DocumentTemplate.is_published.is_(True))
                           .order_by(DocumentTemplate.version.desc()).first())
            if replacement is not None:
                replacement.is_review_active = True
        db.commit()
    except Exception:
        db.rollback()
        restore_uploads(staged)
        raise
    discard_uploads(staged)


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
        template = db.query(DocumentTemplate).filter(DocumentTemplate.workspace_id == body.workspace_id, DocumentTemplate.is_published.is_(True)).order_by(DocumentTemplate.is_review_active.desc(), DocumentTemplate.version.desc()).first()
        if template is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先在模板配置页确认区域用途并保存发布")
    document = db.get(Document, body.document_id)
    if document is None or document.workspace_id != body.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "待审文档不存在")
    if document.file_type != "docx":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "表单模板审查仅支持 .docx 文档")
    if not Path(template.stored_path).is_file() or not Path(document.stored_path).is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "模板或待审文档文件已丢失")
    config = TemplateConfiguration.model_validate(template.config_json)
    try:
        result = review_against_template(config, document.stored_path)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"表单模板审查失败：{exc}") from exc
    if body.ai_field_ids:
        by_id = {block.id: block for block in config.blocks if block.mode == "variable"}
        if any(block_id not in by_id for block_id in body.ai_field_ids):
            raise HTTPException(422, "AI 审查只能选择当前模板中的可变字段")
        try:
            target = extract_template_configuration(document.stored_path)
            target_by_id = {block.id: block for block in target.blocks}
            selected = [(by_id[block_id], target_by_id[block_id].text if block_id in target_by_id else "")
                        for block_id in body.ai_field_ids]
            if sum(len(value) + len(block.requirement_text) for block, value in selected) > 8000:
                raise HTTPException(422, "本次选中字段超过 8000 字，请减少 AI 审查字段")
            result.ai_review = review_template_fields(selected, {block.id: block.label for block in config.blocks})
            for suggestion in result.ai_review.suggestions:
                suggestion.template_content_index = by_id[suggestion.block_id].content_index
                actual = target_by_id.get(suggestion.block_id)
                suggestion.document_content_index = actual.content_index if actual else None
        except HTTPException:
            raise
        except Exception as exc:  # AI 建议失败不覆盖确定性审查结果。
            logger.warning("DeepSeek 表单建议未完成：%s", type(exc).__name__)
            result.ai_review = TemplateAiReview(
                status="failed", summary="DeepSeek 建议未完成；确定性审查结果仍有效",
                model=settings.deepseek_model, field_ids=body.ai_field_ids,
            )
    review = TemplateReview(
        workspace_id=body.workspace_id,
        template_id=template.id,
        template_version=template.version,
        document_id=document.id,
        result_json={**result.model_dump(), "template_snapshot": _template_out(template).model_dump(mode="json")},
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
    before_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=100),
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
        .filter(TemplateReview.id < before_id if before_id is not None else True)
        .order_by(TemplateReview.created_at.desc(), TemplateReview.id.desc())
        .limit(limit)
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
