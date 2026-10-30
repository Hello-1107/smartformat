"""安全暂存待删除的上传文件，数据库提交失败时可恢复。"""

import re
import uuid
from pathlib import Path

from app.config import settings


def stage_uploads(paths: set[str]) -> list[tuple[Path, Path]]:
    staged: list[tuple[Path, Path]] = []
    storage_root = settings.storage_path.resolve()
    try:
        for path in paths:
            original = Path(path)
            # 只处理本应用生成的直属上传文件，避免误删任意路径或符号链接。
            if (original.parent.resolve() != storage_root or original.is_symlink()
                    or not re.fullmatch(r"[0-9a-f]{32}\.(docx|pdf)", original.name, re.I)
                    or not original.is_file()):
                continue
            temporary = original.with_name(f"{original.name}.deleting-{uuid.uuid4().hex}")
            original.replace(temporary)
            staged.append((original, temporary))
    except Exception:
        restore_uploads(staged)
        raise
    return staged


def restore_uploads(staged: list[tuple[Path, Path]]) -> None:
    for original, temporary in reversed(staged):
        if temporary.is_file():
            temporary.replace(original)


def discard_uploads(staged: list[tuple[Path, Path]]) -> None:
    for _original, temporary in staged:
        temporary.unlink(missing_ok=True)
