"""审查路由：对文档执行规则引擎，产出违规报告。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import CheckResult, Document, Rule, User
from app.schemas.check import CheckCreate, CheckOut, CheckSummary, Violation
from app.schemas.document import ParsedDocument
from app.schemas.rule import RuleSet
from app.services.checker import run_check

router = APIRouter(prefix="/checks", tags=["checks"])


def _to_out(check: CheckResult) -> CheckOut:
    return CheckOut(
        id=check.id,
        workspace_id=check.workspace_id,
        document_id=check.document_id,
        rule_id=check.rule_id,
        status=check.status,
        violations=[Violation.model_validate(v) for v in check.violations_json],
        summary=CheckSummary.model_validate(check.summary_json),
        created_at=check.created_at,
    )


@router.post("", response_model=CheckOut, status_code=status.HTTP_201_CREATED)
def run_check_endpoint(
    body: CheckCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CheckOut:
    require_membership(db, user, body.workspace_id)

    doc = db.get(Document, body.document_id)
    if doc is None or doc.workspace_id != body.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    rule = db.get(Rule, body.rule_id)
    if rule is None or rule.workspace_id != body.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    if doc.parsed_json is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文档尚未解析")

    parsed = ParsedDocument.model_validate(doc.parsed_json)
    ruleset = RuleSet.model_validate(rule.ruleset_json)
    violations, summary = run_check(parsed, ruleset)

    check = CheckResult(
        workspace_id=body.workspace_id,
        document_id=doc.id,
        rule_id=rule.id,
        status="done",
        violations_json=[v.model_dump() for v in violations],
        summary_json=summary.model_dump(),
        created_by=user.id,
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return _to_out(check)


@router.get("", response_model=list[CheckOut])
def list_checks(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CheckOut]:
    require_membership(db, user, workspace_id)
    checks = (
        db.query(CheckResult)
        .filter(CheckResult.workspace_id == workspace_id)
        .order_by(CheckResult.created_at.desc())
        .all()
    )
    return [_to_out(c) for c in checks]


@router.get("/{check_id}", response_model=CheckOut)
def get_check(
    check_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> CheckOut:
    check = db.get(CheckResult, check_id)
    if check is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "审查结果不存在")
    require_membership(db, user, check.workspace_id)
    return _to_out(check)
