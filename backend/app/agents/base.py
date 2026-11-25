"""
The contract between the orchestrator (SCRUM-21) and the agents
(Client SCRUM-22, Lawyer SCRUM-23, Judge Support SCRUM-25).

An agent receives an AgentContext (the shared workflow state it needs) and
returns an AgentResult. It talks to the model only through the ModelGateway
it is given, so agents never depend on Ollama directly (SCRUM-20).

To hand work to another agent, return AgentResult(handoff_to="lawyer",
handoff_reason="..."). The orchestrator decides whether the handoff is
allowed for the current user's role and runs the next agent with
`handoff_from` and `previous_outputs` filled in.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol
from uuid import UUID

from app.llm.gateway import ModelGateway

# Agent identifiers used everywhere (API, permissions, state).
CLIENT_AGENT = "client"
LAWYER_AGENT = "lawyer"
JUDGE_SUPPORT_AGENT = "judge_support"
ALL_AGENTS = (CLIENT_AGENT, LAWYER_AGENT, JUDGE_SUPPORT_AGENT)


@dataclass
class AgentContext:
    message: str
    intent: str
    user_roles: frozenset[str]
    history: list[dict[str, str]] = field(default_factory=list)  # [{"role": "user"|"assistant", "content": ...}]
    sources: list[dict[str, Any]] = field(default_factory=list)  # retrieved legal sources
    conversation_id: str | None = None
    handoff_from: str | None = None
    handoff_reason: str | None = None
    previous_outputs: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class AgentResult:
    content: str
    citations: list[dict[str, Any]] = field(default_factory=list)
    handoff_to: str | None = None
    handoff_reason: str | None = None
    model_run_id: UUID | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


class Agent(Protocol):
    name: str
    description: str

    def run(self, context: AgentContext, gateway: ModelGateway) -> AgentResult: ...
