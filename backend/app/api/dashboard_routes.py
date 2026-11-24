from fastapi import APIRouter, Depends
from sqlalchemy import func, select, distinct
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.user import User
from app.models.role import Role
from app.models.user_role import UserRole
from app.models.knowledge_source import KnowledgeSource
from app.models.knowledge_document import KnowledgeDocument


router = APIRouter(
    prefix="/api/v1",
    tags=["Dashboards"],
)


@router.get("/client/dashboard")
def client_dashboard(
    current_user: User = Depends(require_roles("CLIENT")),
):
    return {
        "dashboard": "Client Dashboard",
        "message": "Welcome to your LawPilot AI client workspace.",
        "user_id": str(current_user.id),
        "role": "CLIENT",
    }


@router.get("/lawyer/dashboard")
def lawyer_dashboard(
    current_user: User = Depends(require_roles("LAWYER")),
):
    return {
        "dashboard": "Lawyer Dashboard",
        "message": "Welcome to your LawPilot AI lawyer workspace.",
        "user_id": str(current_user.id),
        "role": "LAWYER",
    }


@router.get("/judge/dashboard")
def judge_dashboard(
    current_user: User = Depends(require_roles("JUDGE")),
):
    return {
        "dashboard": "Judge Dashboard",
        "message": "Welcome to your LawPilot AI judge workspace.",
        "user_id": str(current_user.id),
        "role": "JUDGE",
    }


@router.get("/admin/dashboard")
def admin_dashboard(
    current_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    total_users = db.scalar(
        select(func.count(User.id))
    ) or 0

    def count_role(role_code: str) -> int:
        return db.scalar(
            select(func.count(distinct(UserRole.user_id)))
            .join(Role, UserRole.role_id == Role.id)
            .where(Role.code == role_code)
        ) or 0

    total_sources = db.scalar(
        select(func.count(KnowledgeSource.id))
    ) or 0

    total_documents = db.scalar(
        select(func.count(KnowledgeDocument.id))
    ) or 0

    document_status_counts = db.execute(
        select(
            KnowledgeDocument.processing_status,
            func.count(KnowledgeDocument.id),
        ).group_by(KnowledgeDocument.processing_status)
    ).all()

    documents_by_status = {
        status: count
        for status, count in document_status_counts
    }

    return {
        "dashboard": "Admin Dashboard",
        "message": "Welcome to the LawPilot AI administration workspace.",
        "user_id": str(current_user.id),
        "role": "ADMIN",

        "stats": {
            "total_users": total_users,
            "clients": count_role("CLIENT"),
            "lawyers": count_role("LAWYER"),
            "judges": count_role("JUDGE"),
            "admins": count_role("ADMIN"),
            "legal_sources": total_sources,
            "documents": total_documents,
            "documents_by_status": documents_by_status,
        },
    }