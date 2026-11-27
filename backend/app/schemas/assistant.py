"""Request/response models for /api/v1/assistant (SCRUM-21 orchestrator)."""

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000,
                         examples=["Can my landlord evict me without notice?"])
    # Optional: ask for one agent ("client", "lawyer", "judge_support").
    # Left empty, the orchestrator picks the best agent the user may use.
    agent: str | None = Field(default=None, examples=[None])
    # Continue an existing conversation (earlier turns are given to the agent).
    conversation_id: UUID | None = None
    use_knowledge_base: bool = True


class Citation(BaseModel):
    ref: int
    chunk_id: str | None = None
    source_title: str | None = None
    citation: str | None = None
    url: str | None = None
    page_number: int | None = None
    section_ref: str | None = None
    # SCRUM-26: verified | failed | not_cited | unverified
    verification_status: str = "unverified"
    verification_issues: list[str] = []
    verification_details: list[str] = []


class Handoff(BaseModel):
    from_agent: str | None = Field(default=None, alias="from")
    to_agent: str | None = Field(default=None, alias="to")
    reason: str | None = None
    accepted: bool
    rejected_because: str | None = None

    model_config = {"populate_by_name": True}


class ChatResponse(BaseModel):
    request_id: str
    conversation_id: UUID | None
    # The saved assistant answer; use it to send feedback (SCRUM-29).
    message_id: UUID | None = None
    status: str                      # completed | degraded | rejected | failed
    # SCRUM-27: only True for a completed answer whose citations all verified
    # and whose sources do not conflict. `notice` says why when it is False.
    reliable: bool = False
    notice: str | None = None
    answer: str
    answered_by: str | None
    intent: str | None
    route_reason: str | None
    citations: list[Citation] = []
    handoffs: list[Handoff] = []
    warnings: list[str] = []
    verification: dict[str, Any] = {}
    conflicts: list[dict[str, Any]] = []
    trace: list[str] = []


class AgentInfo(BaseModel):
    name: str
    description: str


class AgentListResponse(BaseModel):
    roles: list[str]
    agents: list[AgentInfo]
