"""Request/response models for /api/v1/assistant (SCRUM-21 orchestrator)."""

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
    status: str                      # completed | degraded | rejected | failed
    answer: str
    answered_by: str | None
    intent: str | None
    route_reason: str | None
    citations: list[Citation] = []
    handoffs: list[Handoff] = []
    warnings: list[str] = []
    trace: list[str] = []


class AgentInfo(BaseModel):
    name: str
    description: str


class AgentListResponse(BaseModel):
    roles: list[str]
    agents: list[AgentInfo]
