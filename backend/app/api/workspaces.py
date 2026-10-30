"""工作区路由。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import Document, User, Workspace, WorkspaceMember
from app.models.template_audit import DocumentTemplate
from app.services.deletion import discard_uploads, restore_uploads, stage_uploads
from app.schemas.workspace import WorkspaceCreate, WorkspaceOut

router = APIRouter(prefix="/workspaces", tags=["workspaces"])


def _to_out(workspace: Workspace, role: str) -> WorkspaceOut:
    return WorkspaceOut(
        id=workspace.id,
        name=workspace.name,
        owner_id=workspace.owner_id,
        role=role,
        created_at=workspace.created_at,
    )


@router.get("", response_model=list[WorkspaceOut])
def list_workspaces(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[WorkspaceOut]:
    rows = (
        db.query(Workspace, WorkspaceMember.role)
        .join(WorkspaceMember, WorkspaceMember.workspace_id == Workspace.id)
        .filter(WorkspaceMember.user_id == user.id)
        .all()
    )
    return [_to_out(w, role) for w, role in rows]


@router.post("", response_model=WorkspaceOut, status_code=status.HTTP_201_CREATED)
def create_workspace(
    body: WorkspaceCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkspaceOut:
    workspace = Workspace(name=body.name, owner_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(
        WorkspaceMember(workspace_id=workspace.id, user_id=user.id, role="owner")
    )
    db.commit()
    db.refresh(workspace)
    return _to_out(workspace, "owner")


@router.get("/{workspace_id}", response_model=WorkspaceOut)
def get_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> WorkspaceOut:
    member = require_membership(db, user, workspace_id)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "工作区不存在")
    return _to_out(workspace, member.role)


@router.delete("/{workspace_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_workspace(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    member = require_membership(db, user, workspace_id)
    workspace = db.get(Workspace, workspace_id)
    if workspace is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "工作区不存在")
    if member.role != "owner" or workspace.owner_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "仅工作区所有者可以删除工作区")

    paths = {row[0] for model in (Document, DocumentTemplate)
             for row in db.query(model.stored_path).filter(model.workspace_id == workspace_id).all()}
    shared = {row[0] for model in (Document, DocumentTemplate)
              for row in db.query(model.stored_path).filter(model.workspace_id != workspace_id, model.stored_path.in_(paths)).all()}
    staged = stage_uploads(paths - shared)
    try:
        db.delete(workspace)
        db.commit()
    except Exception:
        db.rollback()
        restore_uploads(staged)
        raise
    discard_uploads(staged)
