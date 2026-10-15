"""文件存储工具。"""

import uuid
from pathlib import Path

from app.config import settings


def save_upload(content: bytes, filename: str) -> tuple[str, str]:
    """保存上传文件，返回 (绝对路径, 磁盘文件名)。"""
    ext = Path(filename).suffix or ".docx"
    disk_name = f"{uuid.uuid4().hex}{ext}"
    path = settings.storage_path / disk_name
    path.write_bytes(content)
    return str(path), disk_name
