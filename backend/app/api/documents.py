"""文档路由：上传、解析、列表、下载、删除。

上传走「原始二进制请求体」（不用 multipart），因此不依赖 python-multipart：
  POST /api/documents?workspace_id=1&filename=a.docx
  body: docx 原始字节
"""

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.deps import get_current_user, require_membership
from app.models import Document, User
from app.schemas.document import DocumentDetail, DocumentOut, ParsedDocument
from app.services.docx_parser import parse_docx
from app.services.storage import save_upload

router = APIRouter(prefix="/documents", tags=["documents"])

ALLOWED_SUFFIX = ".docx"


def _to_detail(doc: Document) -> DocumentDetail:
    parsed = None
    if doc.parsed_json:
        parsed = ParsedDocument.model_validate(doc.parsed_json)
    return DocumentDetail(
        id=doc.id,
        workspace_id=doc.workspace_id,
        filename=doc.filename,
        size=doc.size,
        created_at=doc.created_at,
        parsed=parsed,
    )


@router.post("", response_model=DocumentDetail, status_code=status.HTTP_201_CREATED)
async def upload_document(
    request: Request,
    workspace_id: int,
    filename: str = "upload.docx",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentDetail:
    require_membership(db, user, workspace_id)
    if not filename.lower().endswith(ALLOWED_SUFFIX):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "仅支持 .docx 文件")
    content = await request.body()
    if not content:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "文件为空")
    stored_path, _ = save_upload(content, filename)
    try:
        parsed = parse_docx(stored_path)
    except Exception as exc:  # noqa: BLE001 - 解析失败应提示用户而非 500
        Path(stored_path).unlink(missing_ok=True)
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, f"解析失败：{exc}"
        ) from exc

    doc = Document(
        workspace_id=workspace_id,
        filename=filename,
        stored_path=stored_path,
        size=len(content),
        parsed_json=parsed.model_dump(),
        created_by=user.id,
    )
    db.add(doc)
    db.commit()
    db.refresh(doc)
    return _to_detail(doc)


@router.get("", response_model=list[DocumentOut])
def list_documents(
    workspace_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> list[DocumentOut]:
    require_membership(db, user, workspace_id)
    docs = (
        db.query(Document)
        .filter(Document.workspace_id == workspace_id)
        .order_by(Document.created_at.desc())
        .all()
    )
    return [DocumentOut.model_validate(d) for d in docs]


@router.get("/{document_id}", response_model=DocumentDetail)
def get_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> DocumentDetail:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    require_membership(db, user, doc.workspace_id)
    return _to_detail(doc)


@router.get("/{document_id}/download")
def download_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> FileResponse:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    require_membership(db, user, doc.workspace_id)
    if not Path(doc.stored_path).exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文件已丢失")
    return FileResponse(doc.stored_path, filename=doc.filename)


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
) -> None:
    doc = db.get(Document, document_id)
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "文档不存在")
    require_membership(db, user, doc.workspace_id)
    Path(doc.stored_path).unlink(missing_ok=True)
    db.delete(doc)
    db.commit()
