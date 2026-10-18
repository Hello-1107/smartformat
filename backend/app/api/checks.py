"""审查路由：对文档执行规则引擎，产出违规报告。"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import CheckResult, Document, Rule, User
from app.schemas.check import (
    BatchCheckCreate,
    BatchCheckOut,
    CheckCreate,
    CheckOut,
    CheckSummary,
    Violation,
)
from app.schemas.document import ParsedDocument, PARSER_VERSION
from app.schemas.rule import RuleSet
from app.services.checker import run_check
from app.services.docx_parser import parse_docx
from pathlib import Path
import hashlib
import json

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
        ruleset_snapshot=check.ruleset_snapshot,
    )


def _build_check(
    *, document: Document, rule: Rule, workspace_id: int, user_id: int
) -> CheckResult:
    """执行一次确定性审查并返回尚未持久化的结果。"""
    if document.file_type != "docx":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "格式审查仅支持 .docx 文档")
    if document.parsed_json is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"文档「{document.filename}」尚未解析")
    if not Path(document.stored_path).is_file():
        raise HTTPException(404, "文档文件已丢失")
    if document.parsed_json.get("parser_version") != PARSER_VERSION:
        document.parsed_json = parse_docx(document.stored_path).model_dump()
    parsed = ParsedDocument.model_validate(document.parsed_json)
    ruleset = RuleSet.model_validate(rule.ruleset_json)
    try:
        violations, summary = run_check(parsed, ruleset)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return CheckResult(
        workspace_id=workspace_id,
        document_id=document.id,
        rule_id=rule.id,
        status="done",
        violations_json=[v.model_dump() for v in violations],
        summary_json=summary.model_dump(),
        ruleset_snapshot={"ruleset": ruleset.model_dump(exclude_none=True), "parser_version": PARSER_VERSION,
                          "hash": hashlib.sha256(json.dumps(rule.ruleset_json, sort_keys=True).encode()).hexdigest()},
        created_by=user_id,
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
    check = _build_check(
        document=doc,
        rule=rule,
        workspace_id=body.workspace_id,
        user_id=user.id,
    )
    db.add(check)
    db.commit()
    db.refresh(check)
    return _to_out(check)


@router.post("/batch", response_model=BatchCheckOut, status_code=status.HTTP_201_CREATED)
def run_batch_check_endpoint(
    body: BatchCheckCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> BatchCheckOut:
    """以同一规则审查多份文档；先完整校验范围，再一次性写入结果。"""
    require_membership(db, user, body.workspace_id)
    rule = db.get(Rule, body.rule_id)
    if rule is None or rule.workspace_id != body.workspace_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")

    document_ids = list(dict.fromkeys(body.document_ids))
    documents: list[Document] = []
    for document_id in document_ids:
        document = db.get(Document, document_id)
        if document is None or document.workspace_id != body.workspace_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"文档 ID {document_id} 不存在")
        if document.parsed_json is None:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"文档「{document.filename}」尚未解析"
            )
        documents.append(document)

    checks = [
        _build_check(
            document=document,
            rule=rule,
            workspace_id=body.workspace_id,
            user_id=user.id,
        )
        for document in documents
    ]
    db.add_all(checks)
    db.commit()
    for check in checks:
        db.refresh(check)
    results = [_to_out(check) for check in checks]
    return BatchCheckOut(
        checks=results,
        total_documents=len(results),
        compliant_documents=sum(item.summary.compliant for item in results),
        violation_total=sum(item.summary.total for item in results),
    )


@router.get("", response_model=list[CheckOut])
def list_checks(
    workspace_id: int,
    document_id: int | None = None,
    before_id: int | None = None,
    latest_only: bool = False,
    limit: int = Query(default=100, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[CheckOut]:
    require_membership(db, user, workspace_id)
    query = db.query(CheckResult).filter(CheckResult.workspace_id == workspace_id)
    if document_id is not None:
        query = query.filter(CheckResult.document_id == document_id)
    if latest_only:
        latest = db.query(func.max(CheckResult.id)).filter(CheckResult.workspace_id == workspace_id).group_by(CheckResult.document_id)
        query = query.filter(CheckResult.id.in_(latest))
    if before_id is not None:
        query = query.filter(CheckResult.id < before_id)
    checks = query.order_by(CheckResult.id.desc()).limit(limit).all()
    return [_to_out(c) for c in checks]


@router.delete("/{check_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_check(
    check_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    """删除一条格式审查历史，不会影响文档或规则。"""
    check = db.get(CheckResult, check_id)
    if check is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "审查结果不存在")
    require_membership(db, user, check.workspace_id)
    db.delete(check)
    db.commit()


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
