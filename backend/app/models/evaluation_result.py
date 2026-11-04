import uuid
from decimal import Decimal

from sqlalchemy import (
    ForeignKey,
    Numeric,
    String,
    Text,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class EvaluationResult(Base):
    __tablename__ = "evaluation_results"

    id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True), primary_key=True, default=uuid.uuid4
    )

    evaluation_set_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("evaluation_sets.id"),
        nullable=False,
    )
    test_case_key: Mapped[str] = mapped_column(String(150), nullable=False)

    model_run_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid(as_uuid=True),
        ForeignKey("model_runs.id"),
        nullable=True,
    )

    retrieval_metrics: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )
    citation_score: Mapped[Decimal | None] = mapped_column(
        Numeric, nullable=True
    )
    groundedness_score: Mapped[Decimal | None] = mapped_column(
        Numeric, nullable=True
    )

    reviewer_label: Mapped[str] = mapped_column(String(100), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)