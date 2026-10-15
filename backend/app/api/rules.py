"""规则路由：由自然语言生成规则（DeepSeek），支持手动覆写、增删查。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import Rule, User
from app.schemas.rule import RuleCreate, RuleOut, RuleSet
from app.services.deepseek_spec import extract_ruleset

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
