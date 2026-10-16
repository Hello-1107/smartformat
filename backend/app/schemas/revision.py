"""修订后副本的请求契约。

服务端只读取已经落库的审查结果和用户确认的替换文本，绝不在生成副本时调用 AI。
"""

from pydantic import BaseModel, Field


class ContentRepairFix(BaseModel):
    """用户确认后，以固定文本替换内容审查引用。"""

    review_id: int
    issue_index: int = Field(ge=0)
    replacement_text: str = Field(min_length=1, max_length=5000)


class TemplateRepairFix(BaseModel):
    """模板审查项的用户确认值；格式项不需要 replacement_text。"""

    review_id: int
    issue_index: int = Field(ge=0)
    replacement_text: str | None = Field(default=None, max_length=5000)


class RevisedCopyCreate(BaseModel):
    workspace_id: int
    check_id: int | None = None
    format_violation_indexes: list[int] = Field(default_factory=list, max_length=500)
    content_fixes: list[ContentRepairFix] = Field(default_factory=list, max_length=50)
    template_fixes: list[TemplateRepairFix] = Field(default_factory=list, max_length=200)
