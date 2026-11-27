"""
LangGraph orchestrator (SCRUM-21).

    START
      -> classify        intent of the message (rules, then model if unsure)
      -> route           pick the agent; enforce role permissions
      -> retrieve        legal sources the user is allowed to see
      -> run_agent  <-+  call the chosen agent through the ModelGateway
      -> handoff ? ---+  agent asked for another agent: check permission, loop
      -> finalize        answer, citations, status
    END

Short-cuts:  route -> reject      (out of scope, or requested agent forbidden)
             any failure -> fail_safe  (safe message, never a stack trace)

Acceptance criteria:
* Requests are classified and routed correctly       -> classify, route
* Only permitted agents can be accessed by each role -> route, handoff (permissions.py)
* Agent handoffs work correctly                      -> handoff node + MAX_HANDOFFS loop guard
* Shared state is maintained across the workflow     -> OrchestratorState (state.py)
* Failures are handled safely                        -> _guard() on every node, fail_safe node,
                                                        degraded answers when model/retrieval fail
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Callable

from langgraph.graph import END, START, StateGraph

from app.agents.base import AgentContext, AgentResult
from app.agents.registry import AgentRegistry, build_default_registry
from app.llm.gateway import ModelGateway, get_model_gateway
from app.llm.types import ModelError
from app.orchestration import permissions
from app.orchestration.classifier import RequestClassifier
from app.safety.responses import (
    NO_ANSWER_MESSAGE,
    assess_reliability,
    conflict_note,
    detect_conflicts,
)
from app.verification.citations import (
    referenced_numbers,
    stored_sources_from_retrieved,
    verify_citations,
)
from app.orchestration.state import (
    INTENT_CASE_ANALYSIS,
    INTENT_DOCUMENT_DRAFTING,
    INTENT_LEGAL_INFORMATION,
    INTENT_LEGAL_RESEARCH,
    INTENT_OUT_OF_SCOPE,
    MAX_HANDOFFS,
    STATUS_COMPLETED,
    STATUS_DEGRADED,
    STATUS_FAILED,
    STATUS_FORBIDDEN,
    STATUS_REJECTED,
    OrchestratorState,
)

logger = logging.getLogger("app.orchestration")

# (query, roles) -> list of source dicts. Raises on failure.
Retriever = Callable[[str, OrchestratorState], list[dict[str, Any]]]

# Which agent suits each intent best, in order of preference.
INTENT_AGENTS: dict[str, tuple[str, ...]] = {
    INTENT_LEGAL_INFORMATION: ("client", "lawyer", "judge_support"),
    INTENT_LEGAL_RESEARCH: ("lawyer", "judge_support", "client"),
    INTENT_DOCUMENT_DRAFTING: ("lawyer", "client"),
    INTENT_CASE_ANALYSIS: ("judge_support", "lawyer"),
}

OUT_OF_SCOPE_MESSAGE = (
    "I can only help with legal questions, such as understanding your rights, "
    "Indian laws and procedures, legal research or legal documents. "
    "Please rephrase your question if it is about a legal matter."
)
MODEL_UNAVAILABLE_MESSAGE = (
    "The AI assistant is temporarily unavailable, so I could not prepare an answer. "
    "Please try again in a few minutes."
)
FAILED_MESSAGE = (
    "Something went wrong while preparing your answer. Please try again. "
    "If the problem continues, contact the administrator with the request ID."
)


class OrchestrationForbidden(Exception):
    """The caller explicitly asked for an agent their role may not use."""


class LegalOrchestrator:
    def __init__(
        self,
        *,
        gateway: ModelGateway | None = None,
        registry: AgentRegistry | None = None,
        retriever: Retriever | None = None,
        classifier: RequestClassifier | None = None,
        retrieval_top_k: int = 5,
    ) -> None:
        self.gateway = gateway or get_model_gateway()
        self.registry = registry or build_default_registry()
        self.retriever = retriever
        self.classifier = classifier or RequestClassifier(self.gateway)
        self.retrieval_top_k = retrieval_top_k
        self.graph = self._build()

    # ------------------------------------------------------------------ #
    # Public API
    # ------------------------------------------------------------------ #
    def run(
        self,
        *,
        message: str,
        roles,
        user_id: str | None = None,
        requested_agent: str | None = None,
        conversation_id: str | None = None,
        history: list[dict[str, str]] | None = None,
        request_id: str | None = None,
        retriever: Retriever | None = None,
    ) -> OrchestratorState:
        initial: OrchestratorState = {
            "request_id": request_id or str(uuid.uuid4()),
            "user_id": str(user_id) if user_id else "",
            "roles": sorted(permissions.normalise_roles(roles)),
            "message": (message or "").strip(),
            "requested_agent": (requested_agent or None),
            "conversation_id": conversation_id,
            "history": history or [],
            "sources": [],
            "handoff_count": 0,
            "citations": [],
            "status": STATUS_COMPLETED,
            "reliable": False,
            "notice": None,
            "verification": {},
            "conflicts": [],
        }
        config = {"configurable": {"retriever": retriever or self.retriever}}
        try:
            final = self.graph.invoke(initial, config=config)
        except Exception:  # last line of defence: the graph itself broke
            logger.exception("Orchestrator crashed request_id=%s", initial["request_id"])
            final = {**initial, "answer": FAILED_MESSAGE, "status": STATUS_FAILED,
                     "errors": [{"step": "graph", "code": "internal_error"}], "trace": ["graph_failed"],
                     **_unreliable(STATUS_FAILED)}
        logger.info(
            "orchestrator request_id=%s intent=%s agent=%s status=%s handoffs=%s trace=%s",
            final.get("request_id"), final.get("intent"), final.get("answered_by"),
            final.get("status"), final.get("handoff_count"), "->".join(final.get("trace", [])),
        )
        return final

    # ------------------------------------------------------------------ #
    # Graph
    # ------------------------------------------------------------------ #
    def _build(self):
        g = StateGraph(OrchestratorState)
        g.add_node("classify", _guard("classify", self._classify))
        g.add_node("route", _guard("route", self._route))
        g.add_node("retrieve", self._retrieve)  # handles its own failures (degrades)
        g.add_node("run_agent", _guard("run_agent", self._run_agent))
        g.add_node("handoff", _guard("handoff", self._handoff))
        g.add_node("finalize", self._finalize)
        g.add_node("reject", self._reject)
        g.add_node("fail_safe", self._fail_safe)

        g.add_edge(START, "classify")
        g.add_conditional_edges("classify", _next_or_fail("route"), ["route", "fail_safe"])
        g.add_conditional_edges("route", self._after_route, ["retrieve", "reject", "fail_safe"])
        g.add_edge("retrieve", "run_agent")
        g.add_conditional_edges("run_agent", self._after_agent, ["handoff", "finalize", "fail_safe"])
        g.add_conditional_edges("handoff", self._after_handoff, ["run_agent", "finalize", "fail_safe"])
        g.add_edge("finalize", END)
        g.add_edge("reject", END)
        g.add_edge("fail_safe", END)
        return g.compile()

    # ---- nodes -------------------------------------------------------- #
    def _classify(self, state: OrchestratorState) -> dict:
        if not state["message"]:
            return {"intent": INTENT_OUT_OF_SCOPE, "intent_confidence": 1.0,
                    "classified_by": "rules", "trace": ["classify:empty"]}
        c = self.classifier.classify(state["message"])
        return {"intent": c.intent, "intent_confidence": c.confidence,
                "classified_by": c.classified_by, "trace": [f"classify:{c.intent}"]}

    def _route(self, state: OrchestratorState) -> dict:
        roles = state["roles"]
        allowed = permissions.permitted_agents(roles)
        requested = state.get("requested_agent")

        if requested:
            if requested not in self.registry:
                return {"target_agent": None, "status": STATUS_FORBIDDEN,
                        "route_reason": f"unknown agent '{requested}'", "trace": ["route:unknown_agent"]}
            if requested not in allowed:
                return {"target_agent": None, "status": STATUS_FORBIDDEN,
                        "route_reason": f"role(s) {', '.join(roles) or 'none'} may not use the {requested} agent",
                        "trace": ["route:forbidden"]}
            return {"target_agent": requested, "route_reason": "agent selected by user",
                    "trace": [f"route:{requested}"]}

        if not allowed:
            return {"target_agent": None, "status": STATUS_FORBIDDEN,
                    "route_reason": "user has no role with access to an agent", "trace": ["route:no_role"]}

        intent = state.get("intent")
        if intent == INTENT_OUT_OF_SCOPE:
            return {"target_agent": None, "status": STATUS_REJECTED,
                    "route_reason": "message is not a legal question", "trace": ["route:out_of_scope"]}

        for agent in INTENT_AGENTS.get(intent, ()):
            if agent in allowed and agent in self.registry:
                return {"target_agent": agent, "route_reason": f"best permitted agent for {intent}",
                        "trace": [f"route:{agent}"]}

        fallback = permissions.default_agent(roles)
        return {"target_agent": fallback, "route_reason": "default agent for role",
                "trace": [f"route:{fallback}"]}

    def _retrieve(self, state: OrchestratorState, config) -> dict:
        retriever = (config or {}).get("configurable", {}).get("retriever")
        if retriever is None:
            return {"sources": [], "trace": ["retrieve:skipped"]}
        try:
            sources = retriever(state["message"], state)[: self.retrieval_top_k]
        except Exception as exc:  # answer without sources rather than failing
            logger.warning("Retrieval failed request_id=%s: %s", state.get("request_id"), type(exc).__name__)
            return {"sources": [], "warnings": ["retrieval_unavailable"], "trace": ["retrieve:failed"]}
        return {"sources": sources, "trace": [f"retrieve:{len(sources)}"]}

    def _run_agent(self, state: OrchestratorState) -> dict:
        name = state["target_agent"]
        agent = self.registry.get(name)
        if agent is None:
            raise LookupError(f"agent '{name}' is not registered")

        previous = state.get("agent_outputs", [])
        last_handoff = state.get("handoffs", [])[-1] if state.get("handoffs") else None
        ctx = AgentContext(
            message=state["message"],
            intent=state.get("intent", INTENT_LEGAL_INFORMATION),
            user_roles=frozenset(state["roles"]),
            history=state.get("history", []),
            sources=state.get("sources", []),
            conversation_id=state.get("conversation_id"),
            handoff_from=last_handoff["from"] if last_handoff and last_handoff.get("accepted") else None,
            handoff_reason=last_handoff["reason"] if last_handoff and last_handoff.get("accepted") else None,
            previous_outputs=list(previous),
            retrieval_failed="retrieval_unavailable" in state.get("warnings", []),
        )
        try:
            result: AgentResult = agent.run(ctx, self.gateway)
        except ModelError as exc:
            # Model down or timed out. Keep any earlier agent's answer if there is one.
            return {
                "current_agent": name, "handoff_to": None,
                "warnings": [exc.code],
                "errors": [{"step": "run_agent", "agent": name, "code": exc.code}],
                "trace": [f"agent:{name}:model_error"],
            }

        output = {"agent": name, "content": result.content, "citations": result.citations,
                  "metadata": result.metadata}
        update: dict = {
            "current_agent": name,
            "agent_outputs": [output],
            "handoff_to": result.handoff_to,
            "handoff_reason": result.handoff_reason,
            "trace": [f"agent:{name}"],
        }
        if result.model_run_id:
            update["model_run_ids"] = [str(result.model_run_id)]
        return update

    def _handoff(self, state: OrchestratorState) -> dict:
        source, target = state["current_agent"], state["handoff_to"]
        reason = state.get("handoff_reason") or ""
        visited = {o["agent"] for o in state.get("agent_outputs", [])}
        record = {"from": source, "to": target, "reason": reason, "accepted": False}

        if state.get("handoff_count", 0) >= MAX_HANDOFFS:
            record["rejected_because"] = "handoff limit reached"
        elif target in visited:
            record["rejected_because"] = "agent already ran (loop prevented)"
        elif target not in self.registry:
            record["rejected_because"] = "agent not registered"
        elif not permissions.can_use(state["roles"], target):
            record["rejected_because"] = "not permitted for this role"
        else:
            record["accepted"] = True

        update: dict = {"handoffs": [record], "handoff_to": None,
                        "trace": [f"handoff:{source}->{target}:{'ok' if record['accepted'] else 'denied'}"]}
        if record["accepted"]:
            update["target_agent"] = target
            update["handoff_count"] = state.get("handoff_count", 0) + 1
        else:
            update["warnings"] = [f"handoff_to_{target}_not_available"]
        return update

    def _finalize(self, state: OrchestratorState) -> dict:
        outputs = state.get("agent_outputs", [])
        warnings = state.get("warnings", [])
        if not outputs:
            # No agent produced anything (model unavailable on the first agent).
            return {"answer": MODEL_UNAVAILABLE_MESSAGE, "answered_by": None, "citations": [],
                    "status": STATUS_DEGRADED, "trace": ["finalize:no_answer"],
                    **_unreliable(STATUS_DEGRADED, warnings)}
        final = outputs[-1]
        answer = final["content"]
        denied = [h for h in state.get("handoffs", []) if not h.get("accepted")]
        if any(h.get("to") == "lawyer" for h in denied):
            answer += (
                "\n\nNote: preparing a formal legal document needs a qualified advocate. "
                "Please consult a lawyer, who can draft it for your specific situation."
            )
        status = (
            STATUS_DEGRADED
            if (
                any(w in warnings for w in (
                    "retrieval_unavailable",
                    "model_unavailable",
                    "model_timeout",
                    "model_bad_response",
                ))
                or final.get("metadata", {}).get("safe_fallback")
            )
            else STATUS_COMPLETED
        )

        # SCRUM-26: check every citation against the stored sources.
        # SCRUM-27: flag conflicting sources; decide whether the answer is reliable.
        sources = state.get("sources", [])
        citations = final.get("citations", [])
        report = verify_citations(answer, citations, stored_sources_from_retrieved(sources))

        # Hard grounding gate: the prompt alone does not stop a small model
        # from answering from memory. If the answer names law that is not in
        # the retrieved sources, or cites none of them, it is not shown:
        # the user gets "No answer available" instead. Drafts are exempt
        # (they go through second-lawyer review and keep their warnings).
        blocked = self._ungrounded(state, final, report)
        if blocked:
            return {"answer": NO_ANSWER_MESSAGE, "answered_by": final["agent"],
                    "citations": [], "status": STATUS_COMPLETED,
                    "verification": report.summary(), "conflicts": [],
                    "reliable": False, "notice": None,
                    "warnings": blocked, "trace": ["finalize:no_grounded_answer"]}

        conflicts = detect_conflicts(sources)
        answer += conflict_note(conflicts)
        reliability = assess_reliability(
            status=status,
            citations=citations,
            verification=report,
            conflicts=conflicts,
            warnings=warnings,
            safe_fallback=bool(final.get("metadata", {}).get("safe_fallback")),
        )
        update = {"answer": answer, "answered_by": final["agent"],
                  "citations": report.annotate(citations), "status": status,
                  "verification": report.summary(), "conflicts": conflicts,
                  "reliable": reliability.reliable, "notice": reliability.notice,
                  "trace": ["finalize"]}
        if report.has_failures:
            update["warnings"] = ["citation_verification_failed"]
        if report.unsupported_mentions:
            update.setdefault("warnings", []).append("unsupported_provisions")
        if conflicts:
            update.setdefault("warnings", []).append("conflicting_sources")
        return update

    @staticmethod
    def _ungrounded(state: OrchestratorState, final: dict, report) -> list[str]:
        """Warnings explaining why an answer must be withheld; [] if it is grounded."""
        if final.get("metadata", {}).get("safe_fallback"):
            return []  # already a safe message (no evidence / no answer / unavailable)
        if state.get("intent") == INTENT_DOCUMENT_DRAFTING:
            return []
        if report.unsupported_mentions:
            return ["ungrounded_answer_blocked", "unsupported_provisions"]
        if not referenced_numbers(final.get("content", "")):
            return ["ungrounded_answer_blocked", "no_source_cited"]
        return []

    def _reject(self, state: OrchestratorState) -> dict:
        if state.get("status") == STATUS_FORBIDDEN:
            answer = "You do not have access to that assistant."
        else:
            answer = OUT_OF_SCOPE_MESSAGE
        return {"answer": answer, "answered_by": None, "citations": [], "trace": ["reject"],
                **_unreliable(state.get("status") or STATUS_REJECTED)}

    def _fail_safe(self, state: OrchestratorState) -> dict:
        # Keep a partial answer from an earlier agent if one exists, but never
        # present it as reliable.
        outputs = state.get("agent_outputs", [])
        if outputs:
            last = outputs[-1]
            citations = [
                {**c, "verification_status": "unverified", "verification_issues": [],
                 "verification_details": []}
                for c in last.get("citations", [])
            ]
            return {"answer": last["content"], "answered_by": last["agent"],
                    "citations": citations, "status": STATUS_DEGRADED,
                    "trace": ["fail_safe:partial"],
                    "reliable": False,
                    "notice": ("Something went wrong while checking this answer, so it is "
                               "incomplete and its citations are unverified. Do not rely on it "
                               "without independent verification.")}
        return {"answer": FAILED_MESSAGE, "answered_by": None, "citations": [],
                "status": STATUS_FAILED, "trace": ["fail_safe"], **_unreliable(STATUS_FAILED)}

    # ---- edges -------------------------------------------------------- #
    @staticmethod
    def _after_route(state: OrchestratorState) -> str:
        if _failed(state):
            return "fail_safe"
        if state.get("status") in (STATUS_FORBIDDEN, STATUS_REJECTED) or not state.get("target_agent"):
            return "reject"
        return "retrieve"

    @staticmethod
    def _after_agent(state: OrchestratorState) -> str:
        if _failed(state):
            return "fail_safe"
        return "handoff" if state.get("handoff_to") else "finalize"

    @staticmethod
    def _after_handoff(state: OrchestratorState) -> str:
        if _failed(state):
            return "fail_safe"
        last = state.get("handoffs", [])[-1]
        return "run_agent" if last.get("accepted") else "finalize"


# --------------------------------------------------------------------------- #
def _guard(step: str, fn):
    """Turn an unexpected exception in a node into an error entry (-> fail_safe)."""

    def wrapper(state: OrchestratorState) -> dict:
        try:
            return fn(state)
        except Exception as exc:
            logger.exception("Orchestrator step '%s' failed request_id=%s", step, state.get("request_id"))
            return {"errors": [{"step": step, "code": "internal_error", "type": type(exc).__name__}],
                    "trace": [f"{step}:error"]}

    return wrapper


def _unreliable(status: str, warnings=()) -> dict:
    """State keys for an answer that must not be presented as reliable."""
    r = assess_reliability(status=status, citations=[], verification=None,
                           conflicts=[], warnings=warnings, safe_fallback=True)
    return {"reliable": False, "notice": r.notice, "verification": {}, "conflicts": []}


def _failed(state: OrchestratorState) -> bool:
    return any(e.get("code") == "internal_error" for e in state.get("errors", []))


def _next_or_fail(next_node: str):
    return lambda state: "fail_safe" if _failed(state) else next_node
