"""内容审查结果独立存储；新增表兼容已有数据库。"""

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base
from app.models.base import TimestampMixin


class ContentReview(Base, TimestampMixin):
    __tablename__ = "content_reviews"

    id: Mapped[int] = mapped_column(primary_key=True)
    workspace_id: Mapped[int] = mapped_column(
        ForeignKey("workspaces.id", ondelete="CASCADE"), index=True
    )
    document_id: Mapped[int] = mapped_column(
        ForeignKey("documents.id", ondelete="CASCADE"), index=True
    )
    instructions: Mapped[str] = mapped_column(Text, default="")
    model: Mapped[str] = mapped_column(String(100))
    paragraph_count: Mapped[int]
    result_json: Mapped[dict] = mapped_column(JSON)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
