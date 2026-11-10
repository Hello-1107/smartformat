"""从已保存的格式审查结果生成保守的一键修复计划。"""

import hashlib
import json
from pathlib import Path

from docx import Document as WordDocument
from pydantic import BaseModel

from app.schemas.check import Violation
from app.services.revision_copy import RepairError, _apply_format_fixes, is_repairable_format


class SkippedFix(BaseModel):
    index: int
    reason: str


class AutoFormatPlan(BaseModel):
    check_id: int
    document_id: int
    source_sha256: str
    format_violation_indexes: list[int]
    skipped: list[SkippedFix]


def violation_key(item: Violation) -> tuple:
    return item.category, item.field, item.section_index, item.paragraph_index, item.run_index


def build_auto_format_plan(path: str | Path, document_id: int, check_id: int,
                           violations_json: list[dict]) -> AutoFormatPlan:
    source_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
    violations = [Violation.model_validate(item) for item in violations_json]
    by_location: dict[tuple, set[str]] = {}
    font_by_paragraph: dict[tuple, list[Violation]] = {}
    page_size_fields: dict[int | None, set[str]] = {}
    for item in violations:
        by_location.setdefault(violation_key(item), set()).add(json.dumps(item.expected, sort_keys=True, ensure_ascii=False))
        if item.category == "font":
            font_by_paragraph.setdefault((item.paragraph_index, item.field), []).append(item)
        if item.category == "page" and item.field in {"paper", "width_cm", "height_cm"}:
            page_size_fields.setdefault(item.section_index, set()).add(item.field)

    selected: list[int] = []
    skipped: list[SkippedFix] = []
    seen: set[tuple] = set()
    working = WordDocument(str(path))
    for index, item in enumerate(violations):
        key = violation_key(item)
        reason = None
        if item.category not in {"font", "paragraph", "page"} or not is_repairable_format(item):
            reason = "不属于可安全自动修复的格式项"
        elif item.expected is None:
            reason = "缺少确定的目标格式"
        elif len(by_location[key]) > 1:
            reason = "同一位置存在冲突的目标值"
        elif (item.category == "font" and any(
            other.expected != item.expected and (other.run_index is None or item.run_index is None)
            for other in font_by_paragraph[(item.paragraph_index, item.field)]
        )):
            reason = "整段与局部文字的字体要求冲突"
        elif (item.category == "page" and item.field in {"paper", "width_cm", "height_cm"}
              and "paper" in page_size_fields[item.section_index]
              and len(page_size_fields[item.section_index]) > 1):
            reason = "纸张类型与页面尺寸同时冲突，需人工选择"
        elif key in seen:
            reason = "与前一项重复"
        elif len(selected) >= 500:
            reason = "单次最多自动修复 500 项"
        if reason is None:
            try:
                _apply_format_fixes(working, [item])
            except (RepairError, ValueError, KeyError, TypeError) as exc:
                reason = str(exc) or "无法安全定位或应用"
        if reason is None:
            selected.append(index)
            seen.add(key)
        else:
            skipped.append(SkippedFix(index=index, reason=reason))
    return AutoFormatPlan(check_id=check_id, document_id=document_id, source_sha256=source_hash,
                          format_violation_indexes=selected, skipped=skipped)
