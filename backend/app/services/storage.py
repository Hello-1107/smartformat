"""文件存储工具。"""

import uuid
from io import BytesIO
from pathlib import Path
from zipfile import ZipFile, BadZipFile

from fastapi import HTTPException, Request
from starlette.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.config import settings


def validate_docx(content: bytes) -> None:
    try:
        with ZipFile(BytesIO(content)) as archive:
            entries = archive.infolist()
            if len(entries) > settings.max_zip_entries or sum(e.file_size for e in entries) > settings.max_uncompressed_bytes:
                raise HTTPException(413, "文档解压后过大或包含过多部件")
            if any(e.file_size > 1024 * 1024 and e.file_size / max(e.compress_size, 1) > 1000 for e in entries):
                raise HTTPException(413, "文档压缩比异常，请重新保存文档后上传")
            if not {"[Content_Types].xml", "word/document.xml"}.issubset(archive.namelist()):
                raise ValueError("缺少 Word 文档部件")
            xml = archive.read("word/document.xml")
            if b"<!DOCTYPE" in xml or b"<!ENTITY" in xml:
                raise ValueError("不支持包含实体定义的文档")
    except (BadZipFile, ValueError, KeyError) as exc:
        raise HTTPException(400, "请上传有效的 .docx 文件") from exc


async def read_upload(request: Request, kind: str = "docx") -> bytes:
    content = bytearray()
    async for chunk in request.stream():
        if len(content) + len(chunk) > settings.max_upload_bytes:
            raise HTTPException(413, f"文件超过上传限制（{settings.max_upload_bytes // 1024 // 1024} MB）")
        content.extend(chunk)
    if not content:
        raise HTTPException(400, "文件为空")
    result = bytes(content)
    if kind == "docx":
        await run_in_threadpool(validate_docx, result)
    elif kind == "pdf":
        if not result.startswith(b"%PDF-"):
            raise HTTPException(400, "请上传有效的 PDF 文件")
    else:
        raise HTTPException(400, "不支持的文件类型")
    return result


def require_storage_quota(db: Session, workspace_id: int, size: int) -> None:
    from sqlalchemy import func
    from app.models import Document
    from app.models.template_audit import DocumentTemplate
    used = sum(size for model in (Document, DocumentTemplate) for _path, size in db.query(model.stored_path, func.max(model.size)).filter(model.workspace_id == workspace_id).group_by(model.stored_path).all())
    if used + size > settings.workspace_quota_bytes:
        raise HTTPException(413, "工作区存储配额不足，请清理文档或调整配额")


def save_upload(content: bytes, filename: str) -> tuple[str, str]:
    """保存上传文件，返回 (绝对路径, 磁盘文件名)。"""
    ext = Path(filename).suffix or ".docx"
    disk_name = f"{uuid.uuid4().hex}{ext}"
    path = settings.storage_path / disk_name
    path.write_bytes(content)
    return str(path), disk_name
