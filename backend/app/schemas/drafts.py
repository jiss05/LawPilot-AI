
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class DraftCitation(BaseModel):
    ref: int | None = None
    chunk_id: str | None = None
    source_title: str | None = None
    citation: str | None = None
    url: str | None = None


class DraftGenerateRequest(BaseModel):
    matter_id: UUID
    title: str = Field(min_length=1, max_length=255)
    document_type: str = Field(min_length=1, max_length=100)
    case_facts: str = Field(min_length=20)


class DraftUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class DraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    matter_id: UUID
    owner_user_id: UUID
    title: str
    content: str
    citations: list[DraftCitation] = Field(default_factory=list)
    status: str
    version: int
    reviewed_at: datetime | None = None
    exported_at: datetime | None = None
    created_at: datetime
    updated_at: datetime


class DraftVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    draft_id: UUID
    version: int
    title: str
    content: str
    edited_by_user_id: UUID
    created_at: datetime
