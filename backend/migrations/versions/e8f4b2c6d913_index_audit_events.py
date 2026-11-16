"""index audit_events for the admin audit trail

Revision ID: e8f4b2c6d913
Revises: d7e3a91b5c20
Create Date: 2026-11-16 15:00:00

SCRUM-18: GET /api/v1/admin/audit-events filters by target and sorts by
time ("what happened to this edition?", "latest admin actions"). Without
indexes PostgreSQL would read the whole table for every such question.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "e8f4b2c6d913"
down_revision: Union[str, Sequence[str], None] = "d7e3a91b5c20"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index("idx_audit_events_target", "audit_events", ["target_type", "target_id"])
    op.create_index("idx_audit_events_occurred_at", "audit_events", ["occurred_at"])


def downgrade() -> None:
    op.drop_index("idx_audit_events_occurred_at", table_name="audit_events")
    op.drop_index("idx_audit_events_target", table_name="audit_events")
