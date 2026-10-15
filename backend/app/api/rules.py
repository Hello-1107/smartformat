"""规则路由：由自然语言生成规则（DeepSeek），支持手动覆写、增删查。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import Rule, RuleRevision, RuleTemplate, User
from app.schemas.rule import (
    RuleCreate,
    RuleFromTemplateCreate,
    RuleOut,
    RuleRevisionOut,
    RuleSet,
    RuleTemplateCreate,
    RuleTemplateOut,
)
from app.services.deepseek_spec import extract_ruleset
from app.services.rule_templates import get_rule_template, list_rule_templates

router = APIRouter(prefix="/rules", tags=["rules"])


def _to_out(rule: Rule) -> RuleOut:
    return RuleOut(
        id=rule.id,
        workspace_id=rule.workspace_id,
        name=rule.name,
        natural_language=rule.natural_language,
        ruleset=RuleSet.model_validate(rule.ruleset_json),
        created_at=rule.created_at,
    )


def _revision_to_out(revision: RuleRevision) -> RuleRevisionOut:
    return RuleRevisionOut(
        id=revision.id,
        rule_id=revision.rule_id,
        version=revision.version,
        name=revision.name,
        natural_language=revision.natural_language,
        ruleset=RuleSet.model_validate(revision.ruleset_json),
        created_at=revision.created_at,
    )


def _template_to_out(template: RuleTemplate) -> RuleTemplateOut:
    return RuleTemplateOut(
        id=f"workspace:{template.id}",
        name=template.name,
        description=template.description,
        ruleset=RuleSet.model_validate(template.ruleset_json),
        source="workspace",
    )


def _workspace_template_id(template_id: str) -> int | None:
    """只接受前端展示用的 workspace:<正整数> 模板标识。"""
    if not template_id.startswith("workspace:"):
        return None
    value = template_id.removeprefix("workspace:")
    return int(value) if value.isdigit() and int(value) > 0 else None


def _snapshot_rule(db: Session, rule: Rule) -> RuleRevision:
    """将规则当前状态保存为一个新的不可变版本。"""
    db.flush()
    latest = (
        db.query(func.max(RuleRevision.version))
        .filter(RuleRevision.rule_id == rule.id)
        .scalar()
    )
    revision = RuleRevision(
        workspace_id=rule.workspace_id,
        rule_id=rule.id,
        version=(latest or 0) + 1,
        name=rule.name,
        natural_language=rule.natural_language,
        ruleset_json=rule.ruleset_json,
        created_by=rule.created_by,
    )
    db.add(revision)
    return revision


@router.get("/templates", response_model=list[RuleTemplateOut])
def get_templates(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[RuleTemplateOut]:
    """返回内置模板及当前工作区用户保存的模板。"""
    require_membership(db, user, workspace_id)
    custom_templates = (
        db.query(RuleTemplate)
        .filter(RuleTemplate.workspace_id == workspace_id)
        .order_by(RuleTemplate.created_at.desc(), RuleTemplate.id.desc())
        .all()
    )
    return [*list_rule_templates(), *[_template_to_out(item) for item in custom_templates]]


@router.post("/templates", response_model=RuleTemplateOut, status_code=status.HTTP_201_CREATED)
def create_template(
    body: RuleTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RuleTemplateOut:
    """保存由用户配置的规则集，供同一工作区后续复用。"""
    require_membership(db, user, body.workspace_id)
    template = RuleTemplate(
        workspace_id=body.workspace_id,
        name=body.name.strip(),
        description=body.description.strip(),
        ruleset_json=body.ruleset.model_dump(exclude_none=True),
        created_by=user.id,
    )
    db.add(template)
    db.commit()
    db.refresh(template)
    return _template_to_out(template)


@router.delete("/templates/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_template(
    template_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    template = db.get(RuleTemplate, template_id)
    if template is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "自定义模板不存在")
    require_membership(db, user, template.workspace_id)
    db.delete(template)
    db.commit()


@router.post("/from-template", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule_from_template(
    body: RuleFromTemplateCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RuleOut:
    require_membership(db, user, body.workspace_id)
    template = get_rule_template(body.template_id)
    template_name: str
    ruleset: RuleSet
    if template is not None:
        template_name = template.name
        ruleset = template.ruleset
        natural_language = f"内置模板：{template.name}"
    else:
        template_id = _workspace_template_id(body.template_id)
        if template_id is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "规则模板不存在")
        workspace_template = db.get(RuleTemplate, template_id)
        if workspace_template is None or workspace_template.workspace_id != body.workspace_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "规则模板不存在")
        template_name = workspace_template.name
        ruleset = RuleSet.model_validate(workspace_template.ruleset_json)
        natural_language = f"工作区模板：{workspace_template.name}"

    rule = Rule(
        workspace_id=body.workspace_id,
        name=body.name or template_name,
        natural_language=natural_language,
        ruleset_json=ruleset.model_dump(exclude_none=True),
        created_by=user.id,
    )
    db.add(rule)
    _snapshot_rule(db, rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.post("", response_model=RuleOut, status_code=status.HTTP_201_CREATED)
def create_rule(
    body: RuleCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RuleOut:
    require_membership(db, user, body.workspace_id)
    try:
        ruleset = extract_ruleset(body.natural_language)
    except ValueError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, f"DeepSeek 调用失败：{exc}"
        ) from exc

    rule = Rule(
        workspace_id=body.workspace_id,
        name=body.name or ruleset.name,
        natural_language=body.natural_language,
        ruleset_json=ruleset.model_dump(exclude_none=True),
        created_by=user.id,
    )
    db.add(rule)
    _snapshot_rule(db, rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.get("", response_model=list[RuleOut])
def list_rules(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[RuleOut]:
    require_membership(db, user, workspace_id)
    rules = (
        db.query(Rule)
        .filter(Rule.workspace_id == workspace_id)
        .order_by(Rule.created_at.desc())
        .all()
    )
    return [_to_out(r) for r in rules]


@router.get("/{rule_id}", response_model=RuleOut)
def get_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RuleOut:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    require_membership(db, user, rule.workspace_id)
    return _to_out(rule)


@router.put("/{rule_id}/ruleset", response_model=RuleOut)
def update_ruleset(
    rule_id: int,
    ruleset: RuleSet,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RuleOut:
    """手动覆写提取出的规则（无需再次调用 DeepSeek）。"""
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    require_membership(db, user, rule.workspace_id)
    rule.ruleset_json = ruleset.model_dump(exclude_none=True)
    rule.name = ruleset.name or rule.name
    _snapshot_rule(db, rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.get("/{rule_id}/versions", response_model=list[RuleRevisionOut])
def list_rule_revisions(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[RuleRevisionOut]:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    require_membership(db, user, rule.workspace_id)
    revisions = (
        db.query(RuleRevision)
        .filter(RuleRevision.rule_id == rule.id)
        .order_by(RuleRevision.version.desc())
        .all()
    )
    return [_revision_to_out(revision) for revision in revisions]


@router.put("/{rule_id}/versions/{version}/restore", response_model=RuleOut)
def restore_rule_revision(
    rule_id: int,
    version: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> RuleOut:
    """恢复历史版本，并将恢复后的状态另存为新版本，保证历史不被覆写。"""
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    require_membership(db, user, rule.workspace_id)
    revision = (
        db.query(RuleRevision)
        .filter(RuleRevision.rule_id == rule.id, RuleRevision.version == version)
        .one_or_none()
    )
    if revision is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则版本不存在")

    rule.name = revision.name
    rule.natural_language = revision.natural_language
    rule.ruleset_json = RuleSet.model_validate(revision.ruleset_json).model_dump(
        exclude_none=True
    )
    _snapshot_rule(db, rule)
    db.commit()
    db.refresh(rule)
    return _to_out(rule)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_rule(
    rule_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    rule = db.get(Rule, rule_id)
    if rule is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    require_membership(db, user, rule.workspace_id)
    db.delete(rule)
    db.commit()
