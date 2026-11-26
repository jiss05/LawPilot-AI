"""SCRUM-21: classification, routing, permissions, handoffs, shared state and safe failures."""

import pytest

from app.agents.base import AgentResult
from app.agents.registry import AgentRegistry, build_default_registry
from app.llm.config import ModelSettings
from app.llm.gateway import ModelGateway
from app.llm.providers.fake import FakeProvider
from app.llm.run_recorder import InMemoryRunRecorder
from app.llm.types import ModelTimeoutError, ModelUnavailableError
from app.orchestration import permissions
from app.orchestration.classifier import RequestClassifier, classify_by_rules
from app.orchestration.graph import (
    FAILED_MESSAGE,
    MODEL_UNAVAILABLE_MESSAGE,
    OUT_OF_SCOPE_MESSAGE,
    LegalOrchestrator,
)


def gateway(replies=None, responder=None):
    s = ModelSettings(provider="fake", max_retries=0, retry_backoff_seconds=0)
    return ModelGateway(s, provider=FakeProvider(replies, responder), recorder=InMemoryRunRecorder(),
                        sleep=lambda _: None)


def orchestrator(gw=None, **kw):
    gw = gw or gateway()
    return LegalOrchestrator(gateway=gw, classifier=RequestClassifier(gw, use_model=False), **kw)

def sample_sources(query, state):
    return [
        {
            "chunk_id": "test-source-1",
            "text": "Relevant legal provisions and principles for testing.",
            "source_title": "Test Legal Authority",
            "citation": "Test citation",
            "url": None,
        }
    ]

# ---------------------------------------------------------------- classification
@pytest.mark.parametrize("message, intent", [
    ("Please draft a legal notice for unpaid rent", "document_drafting"),
    ("Prepare a bail application for my client", "document_drafting"),
    ("List the issues for determination in this suit and summarise the arguments", "case_analysis"),
    ("Find case law on Section 138 of the NI Act", "legal_research"),
    ("Can my employer withhold my salary?", "legal_information"),
    ("Give me a biryani recipe", "out_of_scope"),
])
def test_rule_classification(message, intent):
    assert classify_by_rules(message).intent == intent


def test_model_classifier_used_when_rules_unsure():
    gw = gateway(['{"intent": "legal_research", "confidence": 0.9}'])
    c = RequestClassifier(gw).classify("Something about tenancy disputes generally")
    assert (c.intent, c.classified_by) == ("legal_research", "model")


def test_model_classifier_failure_falls_back_to_rules():
    gw = gateway([ModelUnavailableError("down")])
    c = RequestClassifier(gw).classify("hmm what about this")
    assert c.classified_by == "rules"


def test_model_classifier_invalid_label_falls_back_to_rules():
    gw = gateway(['{"intent": "astrology"}'])
    assert RequestClassifier(gw).classify("hmm what about this").classified_by == "rules"


# ---------------------------------------------------------------- routing
@pytest.mark.parametrize("roles, message, agent", [
    (["CLIENT"], "Can my landlord evict me?", "client"),
    (["CLIENT"], "Find case law on Section 138", "client"),          # best permitted for a client
    (["LAWYER"], "Find case law on Section 138", "lawyer"),
    (["LAWYER"], "Can my landlord evict me?", "client"),             # plain-language question
    (["JUDGE"], "Can my landlord evict me?", "judge_support"),
    (["JUDGE"], "Summarise the arguments in this judgment", "judge_support"),
    (["ADMIN"], "Summarise the arguments in this judgment", "judge_support"),
    (["LAWYER"], "Draft a legal notice for cheque bounce", "lawyer"),
])
def test_routes_to_best_permitted_agent(roles, message, agent):
    state = orchestrator(retriever=sample_sources).run(message=message, roles=roles)
    assert state["answered_by"] == agent
    assert state["status"] == "completed"
    assert agent in permissions.permitted_agents(roles)


@pytest.mark.parametrize("roles, requested", [
    (["CLIENT"], "lawyer"), (["CLIENT"], "judge_support"),
    (["LAWYER"], "judge_support"), (["JUDGE"], "lawyer"), ([], "client"),
])
def test_forbidden_agent_is_refused_without_model_call(roles, requested):
    gw = gateway()
    state = orchestrator(gw).run(message="Explain bail", roles=roles, requested_agent=requested)
    assert state["status"] == "forbidden"
    assert state["answered_by"] is None
    assert gw.provider.calls == []


def test_requested_permitted_agent_is_used():
    state = orchestrator().run(message="Explain bail", roles=["LAWYER"], requested_agent="lawyer")
    assert state["answered_by"] == "lawyer" and state["route_reason"] == "agent selected by user"


def test_unknown_agent_is_refused():
    state = orchestrator().run(message="Explain bail", roles=["ADMIN"], requested_agent="hacker")
    assert state["status"] == "forbidden"


def test_out_of_scope_rejected_without_model_call():
    gw = gateway()
    state = orchestrator(gw).run(message="Write a poem about cricket", roles=["CLIENT"])
    assert state["status"] == "rejected" and state["answer"] == OUT_OF_SCOPE_MESSAGE
    assert gw.provider.calls == []


def test_roles_are_case_insensitive():
    assert permissions.permitted_agents(["client"]) == {"client"}
    assert permissions.permitted_agents(["ADMIN"]) == {"client", "lawyer", "judge_support"}


# ---------------------------------------------------------------- handoffs
def test_client_drafting_handoff_denied_for_client_role():
    gw = gateway(["Here is some general information."])
    state = orchestrator(gw, retriever=sample_sources).run(
        message="Draft a legal notice for my unpaid salary",
        roles=["CLIENT"],
    )
    assert state["answered_by"] == "client"
    assert state["handoffs"] == [{"from": "client", "to": "lawyer", "reason": "legal document drafting",
                                  "accepted": False, "rejected_because": "not permitted for this role"}]
    assert "consult a lawyer" in state["answer"]
    assert len(gw.provider.calls) == 1


def test_client_drafting_handoff_accepted_for_admin():
    gw = gateway(["Client draft", "Lawyer final draft"])
    state = orchestrator(gw, retriever=sample_sources).run(
        message="Draft a legal notice",
        roles=["ADMIN"],
        requested_agent="client",
    )
    assert state["handoffs"][0]["accepted"] is True
    assert state["answered_by"] == "lawyer" and state["answer"] == "Lawyer final draft"
    assert [o["agent"] for o in state["agent_outputs"]] == ["client", "lawyer"]
    # The lawyer agent saw the client agent's draft (shared state across the handoff).
    lawyer_request = gw.provider.calls[1][0]
    assert any(m.content == "Client draft" for m in lawyer_request.messages)
    assert "handed to you by the client agent" in lawyer_request.messages[0].content


def test_lawyer_to_client_handoff():
    gw = gateway(["Technical analysis", "Simple explanation"])
    state = orchestrator(gw).run(message="Explain to my client in plain language what bail is",
                                 roles=["LAWYER"], requested_agent="lawyer")
    assert [h["accepted"] for h in state["handoffs"]] == [True]
    assert state["answered_by"] == "client"


class PingPong:
    """Agent that always hands off to its partner -- the loop guard must stop it."""

    def __init__(self, name, partner):
        self.name, self.partner, self.description = name, partner, ""

    def run(self, ctx, gw):
        return AgentResult(content=f"from {self.name}", handoff_to=self.partner, handoff_reason="ping")


def test_handoff_loop_is_prevented():
    registry = AgentRegistry([PingPong("client", "lawyer"), PingPong("lawyer", "client"),
                              PingPong("judge_support", "client")])
    state = orchestrator(registry=registry).run(message="Explain bail", roles=["ADMIN"], requested_agent="client")
    assert [h["accepted"] for h in state["handoffs"]] == [True, False]
    assert state["handoffs"][-1]["rejected_because"] == "agent already ran (loop prevented)"
    assert state["answered_by"] == "lawyer" and state["status"] == "completed"


# ---------------------------------------------------------------- shared state
def test_state_carries_sources_history_and_trace():
    seen = {}

    def retriever(query, state):
        seen["roles"] = state["roles"]
        return [{"chunk_id": "c1", "text": "Section 73 compensation...", "source_title": "Indian Contract Act",
                 "citation": "Section 73", "url": None}]

    gw = gateway(["Answer citing [1]"])
    state = orchestrator(gw, retriever=retriever).run(
        message="Compensation for breach of contract under Section 73?", roles=["LAWYER"],
        history=[{"role": "user", "content": "earlier question"}, {"role": "assistant", "content": "earlier answer"}],
        request_id="req-1")
    assert seen["roles"] == ["LAWYER"]
    assert state["request_id"] == "req-1"
    assert state["citations"][0]["source_title"] == "Indian Contract Act"
    assert state["trace"] == ["classify:legal_research", "route:lawyer", "retrieve:1", "agent:lawyer", "finalize"]
    prompt = gw.provider.calls[0][0].messages
    assert [m.content for m in prompt[1:3]] == ["earlier question", "earlier answer"]
    assert "[1] Indian Contract Act, Section 73" in prompt[-1].content
    assert len(state["model_run_ids"]) == 1


# ---------------------------------------------------------------- failures
def test_retrieval_failure_returns_safe_response():
    def broken(query, state):
        raise ConnectionError("qdrant down")

    gw = gateway(["This answer must not be generated."])

    state = orchestrator(gw, retriever=broken).run(
        message="Explain bail",
        roles=["CLIENT"],
    )

    assert state["status"] == "degraded"
    assert "could not find supporting legal authorities" in state["answer"].lower()
    assert "retrieval_unavailable" in state["warnings"]
    assert state["citations"] == []
    assert gw.provider.calls == []

def test_model_unavailable_gives_safe_message():
    state = orchestrator(
        gateway([ModelUnavailableError("down")]),
        retriever=sample_sources,
    ).run(message="Explain bail", roles=["CLIENT"])

    assert state["status"] == "degraded"
    assert state["answer"] == MODEL_UNAVAILABLE_MESSAGE
    assert state["errors"][0]["code"] == "model_unavailable"

def test_model_failure_after_handoff_keeps_first_answer():
    gw = gateway(["Client draft", ModelTimeoutError("slow")])
    state = orchestrator(gw, retriever=sample_sources).run(
        message="Draft a legal notice",
        roles=["ADMIN"],
        requested_agent="client",
    )
    assert state["answer"] == "Client draft" and state["answered_by"] == "client"
    assert state["status"] == "degraded"


class Crashing:
    name, description = "client", ""

    def run(self, ctx, gw):
        raise KeyError("internal detail")


def test_agent_crash_gives_safe_failure():
    registry = AgentRegistry([Crashing()])
    state = orchestrator(registry=registry).run(message="Explain bail", roles=["CLIENT"])
    assert state["status"] == "failed" and state["answer"] == FAILED_MESSAGE
    assert "internal detail" not in state["answer"]
    assert state["errors"][0] == {"step": "run_agent", "code": "internal_error", "type": "KeyError"}


def test_default_registry_has_all_agents():
    assert sorted(build_default_registry().names()) == ["client", "judge_support", "lawyer"]
