"""
Matters API (supports SCRUM-24 legal drafting).

    POST /api/v1/matters                  create a matter (lawyers)
    GET  /api/v1/matters                  matters I own or am a member of
    GET  /api/v1/matters/{id}/members     who has access
    POST /api/v1/matters/{id}/members     grant access (owner / matter admin)

Drafts belong to a matter. Granting a lawyer `review` (or `admin`)
permission makes them an authorized reviewer who may approve the matter's
drafts.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.request_id import request_id_of
from app.db.session import get_db
from app.models.matter import Matter
from app.models.matter_member import MatterMember
from app.models.user import User
from app.orchestration import permissions
from app.schemas.matters import (
    MatterCreateRequest,
    MatterMemberAddRequest,
    MatterMemberResponse,
    MatterResponse,
)
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/v1/matters", tags=["Matters"])


def _require_lawyer(user: User) -> None:
    if "LAWYER" not in permissions.roles_of(user):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only lawyers can perform this action.")


def _permission(db: Session, matter: Matter, user: User) -> str | None:
    if matter.owner_user_id == user.id:
        return "owner"
    member = db.scalar(
        select(MatterMember).where(MatterMember.matter_id == matter.id, MatterMember.user_id == user.id)
    )
    return member.permission if member else None


@router.post("", response_model=MatterResponse, status_code=status.HTTP_201_CREATED)
def create_matter(
    body: MatterCreateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_lawyer(current_user)
    matter = Matter(
        title=body.title.strip(),
        jurisdiction=body.jurisdiction.strip(),
        court=body.court,
        matter_reference=body.matter_reference,
        owner_user_id=current_user.id,
        status="active",
    )
    db.add(matter)
    db.flush()
    record_audit(db, actor_user_id=current_user.id, action="matter.created", target_type="matter",
                 target_id=matter.id, request_id=request_id_of(request))
    db.commit()
    db.refresh(matter)
    return MatterResponse.model_validate(matter)


@router.get("", response_model=list[MatterResponse])
def list_matters(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    owned = db.scalars(select(Matter).where(Matter.owner_user_id == current_user.id)).all()
    shared = db.execute(
        select(Matter, MatterMember.permission)
        .join(MatterMember, MatterMember.matter_id == Matter.id)
        .where(MatterMember.user_id == current_user.id, Matter.owner_user_id != current_user.id)
    ).all()
    out = [MatterResponse.model_validate(m) for m in owned]
    out += [MatterResponse.model_validate(m).model_copy(update={"my_permission": p}) for m, p in shared]
    out.sort(key=lambda m: m.created_at, reverse=True)
    return out


def _get_matter(db: Session, matter_id: UUID, user: User) -> tuple[Matter, str]:
    matter = db.get(Matter, matter_id)
    permission = _permission(db, matter, user) if matter else None
    if matter is None or permission is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Matter not found.")
    return matter, permission


@router.get("/{matter_id}/members", response_model=list[MatterMemberResponse])
def list_members(
    matter_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    matter, _ = _get_matter(db, matter_id, current_user)
    rows = db.execute(
        select(User, MatterMember.permission)
        .join(MatterMember, MatterMember.user_id == User.id)
        .where(MatterMember.matter_id == matter.id)
    ).all()
    owner = db.get(User, matter.owner_user_id)
    out = []
    if owner is not None:
        out.append(MatterMemberResponse(user_id=owner.id, email=owner.email,
                                        display_name=owner.display_name, permission="owner"))
    out += [
        MatterMemberResponse(user_id=u.id, email=u.email, display_name=u.display_name, permission=p)
        for u, p in rows
    ]
    return out


@router.post("/{matter_id}/members", response_model=MatterMemberResponse)
def add_member(
    matter_id: UUID,
    body: MatterMemberAddRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    matter, permission = _get_matter(db, matter_id, current_user)
    if permission not in ("owner", "admin"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="Only the matter owner can grant access.")

    user = db.scalar(select(User).where(func.lower(User.email) == body.email.lower()))
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="No active user with that email.")
    if user.id == matter.owner_user_id:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="The owner already has full access.")
    if body.permission in ("write", "review", "admin") and "LAWYER" not in permissions.roles_of(user):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail="Only lawyers can be given write or review access.")

    member = db.scalar(
        select(MatterMember).where(MatterMember.matter_id == matter.id, MatterMember.user_id == user.id)
    )
    if member is None:
        member = MatterMember(matter_id=matter.id, user_id=user.id, permission=body.permission,
                              granted_by=current_user.id)
        db.add(member)
    else:
        member.permission = body.permission

    record_audit(db, actor_user_id=current_user.id, action="matter.member_granted", target_type="matter",
                 target_id=matter.id, metadata={"user_id": str(user.id), "permission": body.permission},
                 request_id=request_id_of(request))
    db.commit()
    return MatterMemberResponse(user_id=user.id, email=user.email, display_name=user.display_name,
                                permission=body.permission)
