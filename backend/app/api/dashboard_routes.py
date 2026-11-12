
from fastapi import APIRouter, Depends

from app.api.dependencies import require_roles
from app.models.user import User


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
):
    return {
        "dashboard": "Admin Dashboard",
        "message": "Welcome to the LawPilot AI administration workspace.",
        "user_id": str(current_user.id),
        "role": "ADMIN",
    }
