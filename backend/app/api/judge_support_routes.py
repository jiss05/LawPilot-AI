"""
Judge Support workspace API (SCRUM-25).

    POST /api/v1/judge-support/case-brief   neutral, source-referenced case brief

Only users whose role may use the judge_support agent (JUDGE, ADMIN) can
call it; everyone else gets 403. Chat with the agent goes through
/api/v1/assistant/chat with agent="judge_support".
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.agents.base import JUDGE_SUPPORT_AGENT
from app.agents.case_brief import build_case_brief
from app.api.assistant_routes import _make_retriever, get_orchestrator
from app.api.dependencies import get_current_user
from app.core.request_id import request_id_of
from app.db.session import get_db
from app.models.user import User
from app.orchestration import permissions
from app.schemas.judge_support import CaseBriefRequest, CaseBriefResponse
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/v1/judge-support", tags=["Judge Support"])

FORBIDDEN_DETAIL = "Only authorized Judge Support users can access this workspace."


def require_judge_support(user: User) -> None:
    if not permissions.can_use(permissions.roles_of(user), JUDGE_SUPPORT_AGENT):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=FORBIDDEN_DETAIL)


@router.post("/case-brief", response_model=CaseBriefResponse)
def case_brief(
    body: CaseBriefRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    require_judge_support(current_user)
    request_id = request_id_of(request)

    brief = build_case_brief(
        body.model_dump(),
        gateway=orchestrator.gateway,
        retriever=_make_retriever(db, current_user) if body.use_knowledge_base else None,
    )

    # Identifiers and counts only - never case text (BRD: minimise logs).
    try:
        record_audit(
            db,
            actor_user_id=current_user.id,
            action="judge_support.case_brief_generated",
            target_type="case_brief",
            target_id=None,
            metadata={
                "facts": len(brief.facts),
                "issues": len(brief.disputed_issues),
                "parties": len(brief.party_arguments),
                "status": brief.status,
            },
            request_id=request_id,
        )
        db.commit()
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        brief.warnings.append("audit_not_saved")

    return CaseBriefResponse(
        request_id=request_id,
        case_title=body.case_title,
        case_number=body.case_number,
        court=body.court,
        status=brief.status,
        reliable=brief.reliable,
        notice=brief.notice,
        facts=brief.facts,
        chronology=brief.chronology,
        undated_fact_ids=brief.undated_fact_ids,
        disputed_issues=brief.disputed_issues,
        party_arguments=brief.party_arguments,
        neutral_summary=brief.neutral_summary,
        legal_sources=brief.legal_sources,
        verification=brief.verification,
        conflicts=brief.conflicts,
        neutrality=brief.neutrality,
        warnings=brief.warnings,
        disclaimer=brief.disclaimer,
    )
