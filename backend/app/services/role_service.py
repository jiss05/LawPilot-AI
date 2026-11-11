
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.role import Role


DEFAULT_ROLES = ("CLIENT", "LAWYER", "JUDGE", "ADMIN")


def seed_roles(db: Session) -> None:
    """Insert default roles if they do not already exist."""

    for role_code in DEFAULT_ROLES:
        existing_role = db.scalar(
            select(Role).where(Role.code == role_code)
        )

        if existing_role is None:
            db.add(Role(code=role_code))

    db.commit()
