"""Request/response models for /api/v1/matters (SCRUM-24 drafting support)."""

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class MatterCreateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    jurisdiction: str = Field(default="India", min_length=1, max_length=100)
    court: str | None = Field(default=None, max_length=300)
    matter_reference: str | None = Field(default=None, max_length=255)


class MatterResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    title: str
    jurisdiction: str
    court: str | None = None
    matter_reference: str | None = None
    status: str
    owner_user_id: UUID
    created_at: datetime
    # The caller's access: owner | read | write | review | admin
    my_permission: str = "owner"


class MatterMemberAddRequest(BaseModel):
    email: EmailStr
    # review: may approve drafts; write: may also create drafts.
    permission: Literal["read", "write", "review", "admin"] = "review"


class MatterMemberResponse(BaseModel):
    user_id: UUID
    email: str
    display_name: str
    permission: str
