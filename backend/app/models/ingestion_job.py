import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, Text, Uuid, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class IngestionJob(Base):
    __tablename__ = "ingestion_jobs"

    __table_args__ = (
        Index("idx_ingestion_jobs_document", "knowledge_document_id"),
        Index("idx_ingestion_jobs_status", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    source_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("knowledge_sources.id"), nullable=True
    )
    source_version_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("source_versions.id"), nullable=True
    )

    # Which file this job processed (migration c4d8e2f1a7b3). NULL is
    # allowed for future jobs that process a whole source at once.
    knowledge_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="SET NULL"),
        nullable=True,
    )

    status: Mapped[str] = mapped_column(String(50), nullable=False)

    started_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    counts: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    initiated_by: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    