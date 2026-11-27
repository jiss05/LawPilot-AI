"""add reviewer approval to drafts (SCRUM-24)

Revision ID: a9c4e7d2b815
Revises: 2280dfb3ea2c
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9c4e7d2b815"
down_revision: Union[str, Sequence[str], None] = "2280dfb3ea2c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "draft_documents",
        sa.Column("approved_by_user_id", sa.Uuid(), nullable=True),
    )
    op.add_column(
        "draft_documents",
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "draft_documents",
        sa.Column("review_notes", sa.Text(), nullable=True),
    )
    op.create_foreign_key(
        "fk_draft_documents_approved_by_user_id_users",
        "draft_documents",
        "users",
        ["approved_by_user_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_draft_documents_approved_by_user_id_users",
        "draft_documents",
        type_="foreignkey",
    )
    op.drop_column("draft_documents", "review_notes")
    op.drop_column("draft_documents", "approved_at")
    op.drop_column("draft_documents", "approved_by_user_id")
