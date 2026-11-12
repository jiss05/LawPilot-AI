from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload, joinedload

from app.db.session import get_db
from app.core.security import decode_access_token
from app.models.user import User
from app.models.user_role import UserRole


bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Validate the JWT and retrieve the authenticated user."""

    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token.",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if credentials is None:
        raise unauthorized

    payload = decode_access_token(credentials.credentials)

    if payload is None:
        raise unauthorized

    user_id = payload.get("sub")

    if not user_id:
        raise unauthorized

    try:
        parsed_user_id = UUID(user_id)
    except (ValueError, TypeError):
        raise unauthorized

    statement = (
        select(User)
        .options(
            selectinload(User.role_assignments).joinedload(UserRole.role)
        )
        .where(User.id == parsed_user_id)
    )

    user = db.scalar(statement)

    if user is None or not user.is_active or not user.email_verified:
        raise unauthorized

    return user


def require_roles(*allowed_roles: str):
    """Allow access only to users with one of the specified roles."""

    def role_checker(
        current_user: User = Depends(get_current_user),
    ) -> User:

        user_roles = {
            assignment.role.code
            for assignment in current_user.role_assignments
            if assignment.role is not None
        }

        if not user_roles.intersection(allowed_roles):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to access this resource.",
            )

        return current_user

    return role_checker
