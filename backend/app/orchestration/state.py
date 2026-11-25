"""
Shared workflow state (SCRUM-21: "Shared state is maintained across the workflow").

Every LangGraph node reads this state and returns only the keys it changes.
List keys marked with `operator.add` are appended to, never overwritten, so
the trace, warnings and handoffs of every step are kept to the end.
"""

from __future__ import annotations

import operator
from typing import Annotated, Any, TypedDict

# Intents the classifier can return.
INTENT_LEGAL_INFORMATION = "legal_information"   # plain explanation of law/rights
INTENT_LEGAL_RESEARCH = "legal_research"         # statutes, case law, precedents
INTENT_DOCUMENT_DRAFTING = "document_drafting"   # notices, petitions, agreements
INTENT_CASE_ANALYSIS = "case_analysis"           # judgments, issues, bench notes
INTENT_OUT_OF_SCOPE = "out_of_scope"             # not a legal question
INTENTS = (
    INTENT_LEGAL_INFORMATION,
    INTENT_LEGAL_RESEARCH,
    INTENT_DOCUMENT_DRAFTING,
    INTENT_CASE_ANALYSIS,
    INTENT_OUT_OF_SCOPE,
)

# Final status of a request.
STATUS_COMPLETED = "completed"
STATUS_DEGRADED = "degraded"       # answered, but a dependency was unavailable
STATUS_REJECTED = "rejected"       # out of scope, nothing generated
STATUS_FORBIDDEN = "forbidden"     # requested agent not allowed for this role
STATUS_FAILED = "failed"           # nothing useful could be produced

MAX_HANDOFFS = 2


class OrchestratorState(TypedDict, total=False):
    # ---- input (set once by the API) ----
    request_id: str
    user_id: str
    roles: list[str]
    message: str
    requested_agent: str | None
    conversation_id: str | None
    history: list[dict[str, str]]

    # ---- classification and routing ----
    intent: str
    intent_confidence: float
    classified_by: str            # "rules" | "model"
    target_agent: str | None
    route_reason: str

    # ---- retrieval ----
    sources: list[dict[str, Any]]

    # ---- agent execution ----
    current_agent: str | None
    handoff_to: str | None
    handoff_reason: str | None
    handoff_count: int
    agent_outputs: Annotated[list[dict[str, Any]], operator.add]
    handoffs: Annotated[list[dict[str, Any]], operator.add]

    # ---- result ----
    answer: str
    answered_by: str | None
    citations: list[dict[str, Any]]
    model_run_ids: Annotated[list[str], operator.add]
    status: str
    warnings: Annotated[list[str], operator.add]
    errors: Annotated[list[dict[str, str]], operator.add]
    trace: Annotated[list[str], operator.add]
