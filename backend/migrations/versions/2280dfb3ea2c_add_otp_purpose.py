
"""add OTP purpose

Revision ID: 2280dfb3ea2c
Revises: f3a7c91d2e60
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "2280dfb3ea2c"
down_revision: Union[str, Sequence[str], None] = "f3a7c91d2e60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "email_otps",
        sa.Column(
            "purpose",
            sa.String(length=30),
            server_default="email_verification",
            nullable=False,
        ),
    )

    op.create_check_constraint(
        "ck_email_otps_purpose",
        "email_otps",
        "purpose IN ('email_verification', 'password_reset')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_email_otps_purpose",
        "email_otps",
        type_="check",
    )
    op.drop_column("email_otps", "purpose")
