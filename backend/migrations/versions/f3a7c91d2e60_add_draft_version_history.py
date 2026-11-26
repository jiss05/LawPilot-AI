
"""add draft version history, citations, and review/export timestamps

Revision ID: f3a7c91d2e60
Revises: e8f4b2c6d913
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f3a7c91d2e60"
down_revision: Union[str, Sequence[str], None] = "e8f4b2c6d913"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add review and export timestamps.
    op.add_column(
        "draft_documents",
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "draft_documents",
        sa.Column("exported_at", sa.DateTime(timezone=True), nullable=True),
    )

    # Store the legal citations used to generate each draft.
    # Existing drafts receive an empty JSON array.
    op.add_column(
        "draft_documents",
        sa.Column(
            "citations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )

    # Store snapshots of each draft version.
    op.create_table(
        "draft_versions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            nullable=False,
        ),
        sa.Column(
            "draft_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("draft_documents.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column(
            "edited_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "draft_id",
            "version",
            name="uq_draft_versions_draft_version",
        ),
    )

    op.create_index(
        "ix_draft_versions_draft_id",
        "draft_versions",
        ["draft_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_draft_versions_draft_id",
        table_name="draft_versions",
    )
    op.drop_table("draft_versions")

    op.drop_column("draft_documents", "citations")
    op.drop_column("draft_documents", "exported_at")
    op.drop_column("draft_documents", "reviewed_at")
