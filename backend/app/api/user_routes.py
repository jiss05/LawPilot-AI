from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy import select, func, or_
from sqlalchemy.orm import Session, selectinload, joinedload

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.models.user_role import UserRole
from app.models.role import Role
from app.schemas.user import UserResponse, ChangePasswordRequest
from app.core.security import hash_password, verify_password


router = APIRouter(
    prefix="/api/v1/users",
    tags=["Users"],
)


@router.get("/me", response_model=UserResponse)
def get_my_profile(
    current_user: User = Depends(get_current_user),
):
    """Return the profile of the currently logged-in user."""

    return current_user


@router.post("/me/change-password")
def change_password(
    request: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    """Change the password of the currently authenticated user."""

    # Verify the current password
    if not verify_password(
        request.current_password,
        current_user.password_hash,
    ):
        raise HTTPException(
            status_code=400,
            detail="Current password is incorrect.",
        )

    # Hash the new password
    new_password_hash = hash_password(request.new_password)

    # Update the user's password hash
    current_user.password_hash = new_password_hash

    db.commit()

    return {
        "message": "Password changed successfully."
    }


@router.get("/admin/list")
def admin_list_users(
    search: str | None = Query(default=None),
    role: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    """Return users for Admin User Management."""

    filters = []

    # Search by name or email
    if search and search.strip():
        search_term = f"%{search.strip()}%"

        filters.append(
            or_(
                User.display_name.ilike(search_term),
                User.email.ilike(search_term),
            )
        )

    # Filter by assigned role
    if role and role.strip():
        role_code = role.strip().upper()

        filters.append(
            User.role_assignments.any(
                UserRole.role.has(Role.code == role_code)
            )
        )

    # Count matching users before pagination
    total = db.scalar(
        select(func.count(User.id)).where(*filters)
    ) or 0

    # Fetch matching users
    statement = (
        select(User)
        .options(
            selectinload(User.role_assignments).joinedload(UserRole.role)
        )
        .where(*filters)
        .order_by(User.created_at.desc())
        .offset(offset)
        .limit(limit)
    )

    users = db.scalars(statement).all()

    # Build response
    results = []

    for user in users:
        assigned_roles = [
            assignment.role.code
            for assignment in user.role_assignments
            if assignment.role is not None
        ]

        role_priority = ("ADMIN", "JUDGE", "LAWYER", "CLIENT")

        primary_role = next(
            (
                role_code
                for role_code in role_priority
                if role_code in assigned_roles
            ),
            assigned_roles[0] if assigned_roles else None,
        )

        results.append(
            {
                "id": str(user.id),
                "display_name": user.display_name,
                "email": user.email,
                "role": primary_role,
                "roles": assigned_roles,
                "is_active": user.is_active,
                "email_verified": user.email_verified,
                "professional_id": user.professional_id,
                "created_at": user.created_at,
            }
        )

    return {
        "total": total,
        "limit": limit,
        "offset": offset,
        "users": results,
    }