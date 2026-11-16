
import uuid

from sqlalchemy import (
    ForeignKey,
    Index,
    Integer,
    Text,
    UniqueConstraint,
    text as sql_text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    __table_args__ = (
        # One chunk_index per FILE (migration c4d8e2f1a7b3). It used to be
        # per edition, which broke if an edition had more than one file.
        UniqueConstraint(
            "knowledge_document_id",
            "chunk_index",
            name="uq_document_chunks_document_index",
        ),
        # Full-text search index used by keyword retrieval (migration
        # d7e3a91b5c20). The expression must match the one in the query.
        Index(
            "idx_document_chunks_fts",
            sql_text("to_tsvector('english', text)"),
            postgresql_using="gin",
        ),
        Index(
            "idx_document_chunks_source_version",
            "source_version_id",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    source_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_versions.id"),
        nullable=False,
    )

    # The exact file this chunk was cut from. Deleting the document row
    # deletes its chunks too (ON DELETE CASCADE).
    knowledge_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_documents.id", ondelete="CASCADE"),
        nullable=False,
    )

    chunk_index: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    text: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    page_number: Mapped[int | None] = mapped_column(
        Integer,
        nullable=True,
    )

    section_ref: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    token_count: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
    )

    chunk_metadata: Mapped[dict] = mapped_column(
        "metadata",
        JSONB,
        default=dict,
        nullable=False,
    )
