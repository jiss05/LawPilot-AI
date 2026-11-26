"""
Assistant API (SCRUM-21): the entry point to the multi-agent orchestrator.

    GET  /api/v1/assistant/agents   agents the logged-in user may use
    POST /api/v1/assistant/chat     send a message; the orchestrator classifies
                                    it, routes it to a permitted agent, retrieves
                                    sources and returns the answer

Roles come from the database through get_current_user, never from the
request body (BRD §9). Asking for an agent the role may not use is a 403.
Conversations and messages are stored in `conversations` / `messages`;
each assistant message links to its model run (model_runs).
"""

from __future__ import annotations

import logging
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.core.request_id import request_id_of
from app.db.session import get_db
from app.models.conversation import Conversation
from app.models.matter import Matter
from app.models.matter_member import MatterMember
from app.models.message import Message
from app.models.user import User
from app.orchestration import permissions
from app.orchestration.graph import LegalOrchestrator
from app.orchestration.state import STATUS_FORBIDDEN
from app.schemas.assistant import (
    AgentInfo,
    AgentListResponse,
    ChatRequest,
    ChatResponse,
    Citation,
    Handoff,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/assistant", tags=["Assistant"])

HISTORY_TURNS = 10

_orchestrator: LegalOrchestrator | None = None


def get_orchestrator() -> LegalOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        _orchestrator = LegalOrchestrator()
    return _orchestrator



def _make_retriever(db: Session, user: User):
    """Search the knowledge base using the user's matter access."""

    def retrieve(query: str, state) -> list[dict]:
        from app.api.research_routes import get_search_service
        from app.rag.store_retriever import access_context_for

        # Matters owned by the user.
        owned_matter_ids = set(
            db.scalars(
                select(Matter.id).where(Matter.owner_user_id == user.id)
            ).all()
        )

        # Matters where the user is a member.
        member_matter_ids = set(
            db.scalars(
                select(MatterMember.matter_id).where(
                    MatterMember.user_id == user.id
                )
            ).all()
        )

        # Combine both access sources.
        matter_ids = frozenset(owned_matter_ids | member_matter_ids)

        response = get_search_service().search(
            db,
            query,
            access=access_context_for(user, matter_ids),
            top_k=5,
        )

        return [
            {
                "chunk_id": str(c.chunk_id),
                "text": c.text,
                "source_title": c.source.source_title,
                "citation": c.source.citation,
                "url": c.source.url,
            }
            for c in response.results
        ]

    return retrieve


@router.get("/agents", response_model=AgentListResponse)
def list_agents(
    current_user: User = Depends(get_current_user),
    orchestrator: LegalOrchestrator = Depends(get_orchestrator),
):
    roles = permissions.roles_of(current_user)
    allowed = permissions.permitted_agents(roles)
    agents = [
        AgentInfo(name=name, description=getattr(orchestrator.registry.get(name), "description", ""))
        for name in orchestrator.registry.names()
        if name in allowed
    ]
    return AgentListResponse(roles=sorted(roles), agents=agents)


@router.post("/chat", response_model=ChatResponse)
def chat(
    body: ChatRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    orchestrator: LegalOrchestrator = Depends(get_orchestrator),
):
    roles = permissions.roles_of(current_user)
    request_id = request_id_of(request)

    conversation = None
    history: list[dict[str, str]] = []
    if body.conversation_id:
        conversation = _owned_conversation(db, body.conversation_id, current_user.id)
        history = _history(db, conversation.id)

    state = orchestrator.run(
        message=body.message,
        roles=roles,
        user_id=str(current_user.id),
        requested_agent=body.agent,
        conversation_id=str(conversation.id) if conversation else None,
        history=history,
        request_id=request_id,
        retriever=_make_retriever(db, current_user) if body.use_knowledge_base else None,
    )

    if state.get("status") == STATUS_FORBIDDEN:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You do not have permission to use this assistant.")

    warnings = list(dict.fromkeys(state.get("warnings", [])))
    try:
        conversation = _save_turn(db, conversation, current_user, roles, body.message, state)
    except Exception:
        db.rollback()
        logger.warning("Could not save conversation turn request_id=%s", request_id, exc_info=True)
        warnings.append("conversation_not_saved")

    return ChatResponse(
        request_id=state.get("request_id", request_id or ""),
        conversation_id=conversation.id if conversation else None,
        status=state.get("status", "failed"),
        answer=state.get("answer", ""),
        answered_by=state.get("answered_by"),
        intent=state.get("intent"),
        route_reason=state.get("route_reason"),
        citations=[Citation(**c) for c in state.get("citations", [])],
        handoffs=[Handoff(**h) for h in state.get("handoffs", [])],
        warnings=warnings,
        trace=state.get("trace", []),
    )


# --------------------------------------------------------------------------- #
def _owned_conversation(db: Session, conversation_id: UUID, user_id) -> Conversation:
    conversation = db.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.owner_user_id == user_id,
            Conversation.deleted_at.is_(None),
        )
    )
    if conversation is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found.")
    return conversation


def _history(db: Session, conversation_id) -> list[dict[str, str]]:
    rows = db.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(HISTORY_TURNS)
    ).all()
    return [
        {"role": "assistant" if m.sender_type == "assistant" else "user", "content": m.content}
        for m in reversed(rows)
    ]


def _save_turn(db, conversation, user, roles, message, state) -> Conversation:
    if conversation is None:
        role_context = state.get("answered_by") or state.get("target_agent") or ",".join(sorted(roles)) or "unknown"
        conversation = Conversation(owner_user_id=user.id, role_context=role_context[:50], title=message[:80])
        db.add(conversation)
        db.flush()
    db.add(Message(conversation_id=conversation.id, sender_type="user", content=message, status="received"))
    run_ids = state.get("model_run_ids") or []
    db.add(Message(
        conversation_id=conversation.id,
        sender_type="assistant",
        content=state.get("answer", ""),
        status=state.get("status", "failed"),
        model_run_id=UUID(run_ids[-1]) if run_ids else None,
    ))
    db.commit()
    return conversation
