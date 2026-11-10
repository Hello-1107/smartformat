"""自动格式修复计划和副本的离线回归测试。"""

from io import BytesIO

import pytest
from docx import Document as WordDocument
from docx.shared import Pt
from fastapi import HTTPException

from app.api.documents import AutoFormatApply, auto_format_copy, auto_format_plan
from app.database import SessionLocal
from app.models import CheckResult, Document, Rule, User, Workspace, WorkspaceMember
from app.schemas.check import Violation
from app.schemas.rule import RuleSet
from app.services.checker import run_check
from app.services.auto_format import build_auto_format_plan
from app.services.docx_parser import parse_docx


def test_auto_format_plan_download_recheck_and_source_unchanged(tmp_path):
    path = tmp_path / "source.docx"
    word = WordDocument()
    paragraph = word.add_paragraph("正文示例")
    paragraph.runs[0].font.size = Pt(16)
    word.save(path)
    source_bytes = path.read_bytes()
    ruleset = RuleSet.model_validate({"name": "正文格式", "body": {"font": {"size": 12}}})
    violations, summary = run_check(parse_docx(path), ruleset)
    assert any(item.field == "size" for item in violations)
    structural = Violation(scope="template_structure", category="template_structure", field="missing_region",
                           expected="第一章", actual=None, message="缺少章节", severity="unknown")

    with SessionLocal() as db:
        user = User(username="auto_format_owner", hashed_password="unused")
        db.add(user)
        db.flush()
        workspace = Workspace(name="自动修复测试", owner_id=user.id)
        db.add(workspace)
        db.flush()
        db.add(WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner"))
        doc = Document(workspace_id=workspace.id, filename="source.docx", stored_path=str(path), size=len(source_bytes))
        rule = Rule(workspace_id=workspace.id, name="正文格式", natural_language="测试", ruleset_json=ruleset.model_dump(exclude_none=True), created_by=user.id)
        db.add_all([doc, rule])
        db.flush()
        check = CheckResult(workspace_id=workspace.id, document_id=doc.id, rule_id=rule.id,
                            violations_json=[*(item.model_dump() for item in violations), structural.model_dump()],
                            summary_json=summary.model_dump(), ruleset_snapshot={"ruleset": ruleset.model_dump(exclude_none=True)})
        db.add(check)
        db.commit()

        plan = auto_format_plan(doc.id, workspace.id, check.id, db, user)
        assert len(plan.format_violation_indexes) == 1
        assert any(item.reason == "不属于可安全自动修复的格式项" for item in plan.skipped)
        response = auto_format_copy(doc.id, AutoFormatApply(workspace_id=workspace.id, check_id=check.id,
                                                            source_sha256=plan.source_sha256), db, user)
        assert response.headers["x-fixed-issues"] == "1"
        assert response.headers["x-remaining-issues"] == "0"
        assert path.read_bytes() == source_bytes
        revised = WordDocument(BytesIO(response.body))
        assert revised.paragraphs[0].runs[0].font.size.pt == 12
        assert len(revised.paragraphs) == 1  # 自动模式不在正文追加修订清单

        changed = WordDocument()
        changed.add_paragraph("文件已经变化")
        changed.save(path)
        with pytest.raises(HTTPException) as error:
            auto_format_copy(doc.id, AutoFormatApply(workspace_id=workspace.id, check_id=check.id,
                                                     source_sha256=plan.source_sha256), db, user)
        assert error.value.status_code == 409


def test_conflicting_paragraph_and_run_font_fixes_are_skipped(tmp_path):
    path = tmp_path / "conflict.docx"
    document = WordDocument()
    document.add_paragraph("冲突文字")
    document.save(path)
    whole = Violation(scope="body", category="font", field="size", expected=12, actual=16,
                      message="整段字号", paragraph_index=0)
    part = whole.model_copy(update={"expected": 14, "message": "局部字号", "run_index": 0})
    plan = build_auto_format_plan(path, 1, 2, [whole.model_dump(), part.model_dump()])
    assert plan.format_violation_indexes == []
    assert all("冲突" in item.reason for item in plan.skipped)
