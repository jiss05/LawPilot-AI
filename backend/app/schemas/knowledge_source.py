
from datetime import date, datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class KnowledgeSourceResponse(BaseModel):
    id: UUID
    title: str
    source_type: str
    publisher: str | None
    canonical_url: str | None
    jurisdiction: str
    trust_tier: str
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class KnowledgeDocumentResponse(BaseModel):
    id: UUID
    source_version_id: UUID
    filename: str
    file_type: str
    sha256: str
    uploaded_by: UUID
    uploaded_at: datetime
    processing_status: str
    visibility: str

    model_config = ConfigDict(from_attributes=True)


# ---------------------------------------------------------------------------
# Source versions (SCRUM-18)
# ---------------------------------------------------------------------------
class VersionDocumentSummary(BaseModel):
    id: UUID
    filename: str
    processing_status: str
    visibility: str
    uploaded_at: datetime
    chunk_count: int


class SourceVersionResponse(BaseModel):
    id: UUID
    source_id: UUID
    version_label: str | None
    published_at: date | None
    retrieved_at: datetime
    status: str  # pending / active / superseded / withdrawn / failed
    content_hash: str
    supersedes_version_id: UUID | None
    documents: list[VersionDocumentSummary] = []


class VersionActionRequest(BaseModel):
    reason: str = Field(min_length=3, max_length=500, examples=["Amendment Act 2024 published"])


class VersionActionResponse(BaseModel):
    version: SourceVersionResponse
    superseded_version_ids: list[UUID] = []
