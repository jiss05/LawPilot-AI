
import uuid
from datetime import date, datetime

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class SourceVersion(Base):
    __tablename__ = "source_versions"

    __table_args__ = (
        CheckConstraint(
            # 'pending' = uploaded but not processed yet (migration c4d8e2f1a7b3)
            "status IN ('pending', 'active', 'superseded', 'withdrawn', 'failed')",
            name="ck_source_versions_status",
        ),
        Index("idx_source_versions_status", "status"),
        Index("idx_source_versions_source", "source_id"),  # migration d7e3a91b5c20
    )

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
    )

    source_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("knowledge_sources.id"),
        nullable=False,
    )

    version_label: Mapped[str | None] = mapped_column(
        String(100),
        nullable=True,
    )

    published_at: Mapped[date | None] = mapped_column(
        Date,
        nullable=True,
    )

    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )

    content_hash: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )

    status: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )

    raw_storage_key: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
    )

    supersedes_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("source_versions.id"),
        nullable=True,
    )
