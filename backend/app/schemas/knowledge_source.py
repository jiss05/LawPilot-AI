
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict


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
