from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)
from app.models.role import Role
from app.models.user import User
from app.models.user_role import UserRole
from app.schemas.auth import UserRegister


def register_user(db: Session, user_data: UserRegister) -> User:
    """Create a pending account and assign its requested public role."""

    email = user_data.email.lower()
    requested_role = user_data.requested_role
    professional_id = user_data.professional_id

    existing_user = db.scalar(
        select(User).where(User.email == email)
    )

    if existing_user:
        raise ValueError(
            "An account with this email already exists."
        )

    if professional_id:
        existing_professional = db.scalar(
            select(User).where(
                User.professional_id == professional_id
            )
        )

        if existing_professional:
            raise ValueError(
                "This professional ID is already registered."
            )

    role = db.scalar(
        select(Role).where(Role.code == requested_role)
    )

    if role is None:
        raise RuntimeError(
            f"{requested_role} role was not found. "
            "Database migration and role seeding are required."
        )

    user = User(
        email=email,
        display_name=user_data.display_name,
        password_hash=hash_password(user_data.password),
        professional_id=professional_id,
        email_verified=False,
        is_active=False,
    )

    try:
        db.add(user)
        db.flush()

        db.add(
            UserRole(
                user_id=user.id,
                role_id=role.id,
            )
        )

        db.commit()
        db.refresh(user)

        return user

    except IntegrityError as error:
        db.rollback()
        raise ValueError(
            "An account with this email or professional ID already exists."
        ) from error

    except Exception:
        db.rollback()
        raise


def authenticate_user(
    db: Session,
    email: str,
    password: str,
) -> User | None:

    user = db.scalar(
        select(User).where(User.email == email.lower())
    )

    if user is None:
        return None

    if not verify_password(password, user.password_hash):
        return None

    if not user.is_active or not user.email_verified:
        return None

    return user


def create_user_token(user: User) -> str:
    return create_access_token(str(user.id))