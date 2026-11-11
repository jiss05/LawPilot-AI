"""add professional id to users

Revision ID: 9abede709c56
Revises: b7c21a9d4f10
Create Date: 2026-11-10 13:31:13.343885

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9abede709c56'
down_revision: Union[str, Sequence[str], None] = 'b7c21a9d4f10'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "professional_id",
            sa.String(length=11),
            nullable=True,
        ),
    )

    op.create_unique_constraint(
        "uq_users_professional_id",
        "users",
        ["professional_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_users_professional_id",
        "users",
        type_="unique",
    )

    op.drop_column(
        "users",
        "professional_id",
    )