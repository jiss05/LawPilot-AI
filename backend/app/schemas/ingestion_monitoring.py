"""Response models for the admin ingestion-monitoring API (SCRUM-18)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class IngestionJobResponse(BaseModel):
    id: UUID
    stage: str | None              # text_extraction / chunking / indexing / activation
    status: str                    # running / completed / failed
    knowledge_document_id: UUID | None
    filename: str | None
    source_id: UUID | None
    source_version_id: UUID | None
    started_at: datetime | None
    finished_at: datetime | None
    duration_ms: int | None
    error_code: str | None         # e.g. CORRUPTED_FILE, VECTOR_STORE_UNAVAILABLE
    error_summary: str | None
    initiated_by: UUID | None
    counts: dict[str, Any] | None


class JobListResponse(BaseModel):
    total: int
    items: list[IngestionJobResponse]


class FailedDocument(BaseModel):
    document_id: UUID
    filename: str
    source_title: str | None
    processing_status: str
    last_error: str | None
    failed_at: datetime | None


class IngestionSummary(BaseModel):
    documents_by_status: dict[str, int]
    versions_by_status: dict[str, int]
    jobs_last_24h: dict[str, int]       # status -> count
    failures_last_24h_by_code: dict[str, int]
    in_progress: int
    failed_documents: list[FailedDocument]
    vector_store: dict[str, Any]


class DocumentStatusResponse(BaseModel):
    document_id: UUID
    filename: str
    processing_status: str
    visibility: str
    source_id: UUID
    source_title: str
    version_id: UUID
    version_label: str | None
    version_status: str
    chunk_count: int
    vector_count: int | None            # None if Qdrant is unreachable
    searchable: bool
    jobs: list[IngestionJobResponse]


class ReprocessRequest(BaseModel):
    document_id: UUID


class ReprocessResponse(BaseModel):
    document_id: UUID
    message: str


class AuditEventResponse(BaseModel):
    id: UUID
    actor_user_id: UUID | None
    actor_email: str | None
    action: str
    target_type: str
    target_id: str | None
    request_id: str | None
    occurred_at: datetime
    metadata: dict[str, Any] | None


class AuditListResponse(BaseModel):
    total: int
    items: list[AuditEventResponse]
