"""工作区 schema。"""

from datetime import datetime

from pydantic import BaseModel, Field


class WorkspaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)


class WorkspaceOut(BaseModel):
    id: int
    name: str
    owner_id: int
    role: str = "owner"
    created_at: datetime

    model_config = {"from_attributes": True}
