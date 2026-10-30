"""工作区与表单模板版本删除的数据库级回归测试。"""

from pathlib import Path
from uuid import uuid4

import pytest
from fastapi import HTTPException

from app.api.template_audits import _next_version, delete_template_version
from app.api.workspaces import delete_workspace
from app.config import settings
from app.database import SessionLocal
from app.models import Document, DocumentTemplate, TemplateReview, User, Workspace, WorkspaceMember
from app.services.deletion import stage_uploads


def _owner_and_workspace(db):
    owner = User(username=f"owner_{uuid4().hex}", hashed_password="unused")
    db.add(owner)
    db.flush()
    workspace = Workspace(name="待删除工作区", owner_id=owner.id)
    db.add(workspace)
    db.flush()
    db.add(WorkspaceMember(workspace_id=workspace.id, user_id=owner.id, role="owner"))
    db.commit()
    return owner, workspace


def _file() -> Path:
    path = settings.storage_path / f"{uuid4().hex}.docx"
    path.write_bytes(b"test")
    return path


def test_delete_version_keeps_shared_file_and_advances_number():
    with SessionLocal() as db:
        owner, workspace = _owner_and_workspace(db)
        path = _file()
        first = DocumentTemplate(workspace_id=workspace.id, version=_next_version(db, workspace.id), name="一",
                                 filename="template.docx", stored_path=str(path), size=4, is_active=False,
                                 is_published=True, is_review_active=False, config_json={})
        second = DocumentTemplate(workspace_id=workspace.id, version=_next_version(db, workspace.id), name="二",
                                  filename="template.docx", stored_path=str(path), size=4, is_active=True,
                                  is_published=True, is_review_active=True, config_json={})
        db.add_all([first, second])
        document_path = _file()
        document = Document(workspace_id=workspace.id, filename="target.docx", stored_path=str(document_path), size=4)
        db.add(document)
        db.flush()
        db.add(TemplateReview(workspace_id=workspace.id, template_id=second.id,
                              document_id=document.id, template_version=2, result_json={}))
        db.commit()
        first_id, second_id, workspace_id, owner_id = first.id, second.id, workspace.id, owner.id
        delete_template_version(second_id, workspace_id, db, owner)
        assert path.is_file()
        assert db.get(DocumentTemplate, second_id) is None
        assert db.query(TemplateReview).filter_by(template_id=second_id).count() == 0
        restored = db.get(DocumentTemplate, first_id)
        assert restored.is_active and restored.is_review_active
        assert _next_version(db, workspace_id) == 3
        db.rollback()
        delete_template_version(first_id, workspace_id, db, db.get(User, owner_id))
        assert not path.exists()
        assert db.query(DocumentTemplate).filter_by(workspace_id=workspace_id).count() == 0
        delete_workspace(workspace_id, db, db.get(User, owner_id))
        assert not document_path.exists()


def test_workspace_delete_owner_only_cascades_and_keeps_shared_file():
    with SessionLocal() as db:
        owner, workspace = _owner_and_workspace(db)
        shared = _file()
        unique = _file()
        other = Workspace(name="保留", owner_id=owner.id)
        guest = User(username=f"guest_{uuid4().hex}", hashed_password="unused")
        db.add_all([other, guest])
        db.flush()
        db.add_all([
            WorkspaceMember(workspace_id=other.id, user_id=owner.id, role="owner"),
            WorkspaceMember(workspace_id=workspace.id, user_id=guest.id, role="member"),
            Document(workspace_id=workspace.id, filename="one.docx", stored_path=str(unique), size=4),
            Document(workspace_id=other.id, filename="two.docx", stored_path=str(shared), size=4),
            DocumentTemplate(workspace_id=workspace.id, version=1, name="共享", filename="template.docx",
                             stored_path=str(shared), size=4, is_active=True, is_published=False,
                             is_review_active=False, config_json={}),
        ])
        db.commit()
        workspace_id, guest_id = workspace.id, guest.id
        with pytest.raises(HTTPException) as error:
            delete_workspace(workspace_id, db, db.get(User, guest_id))
        assert error.value.status_code == 403
        delete_workspace(workspace_id, db, owner)
        assert db.get(Workspace, workspace_id) is None
        assert db.query(TemplateReview).filter_by(workspace_id=workspace_id).count() == 0
        assert not unique.exists()
        assert shared.is_file()
        shared.unlink()


def test_stage_uploads_ignores_files_outside_managed_storage(tmp_path):
    outside = tmp_path / "unrelated.docx"
    outside.write_bytes(b"keep")
    assert stage_uploads({str(outside)}) == []
    assert outside.read_bytes() == b"keep"


def test_failed_template_delete_restores_file_and_version(monkeypatch):
    with SessionLocal() as db:
        owner, workspace = _owner_and_workspace(db)
        path = _file()
        version = DocumentTemplate(workspace_id=workspace.id, version=1, name="保留",
                                   filename="template.docx", stored_path=str(path), size=4,
                                   is_active=True, is_published=False, is_review_active=False, config_json={})
        db.add(version)
        db.commit()
        version_id = version.id
        with monkeypatch.context() as patch:
            patch.setattr(db, "commit", lambda: (_ for _ in ()).throw(RuntimeError("commit failed")))
            with pytest.raises(RuntimeError, match="commit failed"):
                delete_template_version(version_id, workspace.id, db, owner)
        assert path.is_file()
        assert db.get(DocumentTemplate, version_id) is not None
        delete_workspace(workspace.id, db, owner)
