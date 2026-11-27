"""Answers must come only from the uploaded documents; otherwise "No answer available"."""

import pytest

from app.agents.default_agents import _GROUNDING
from app.llm.config import ModelSettings
from app.llm.gateway import ModelGateway
from app.llm.providers.fake import FakeProvider
from app.llm.run_recorder import InMemoryRunRecorder
from app.orchestration.classifier import RequestClassifier
from app.orchestration.graph import LegalOrchestrator
from app.safety.responses import NO_ANSWER_MESSAGE, NO_ANSWER_TOKEN

BAILMENT = [{
    "chunk_id": "ica-148",
    "text": "148. A bailment is the delivery of goods by one person to another "
            "for some purpose, upon a contract that they shall be returned.",
    "source_title": "Indian Contract Act, 1872",
    "citation": "Section 148",
    "url": None,
}]


def run(reply, message="My cousin killed a neighbour, how can he escape?", roles=("CLIENT",)):
    gw = ModelGateway(ModelSettings(provider="fake", max_retries=0, retry_backoff_seconds=0),
                      provider=FakeProvider([reply]), recorder=InMemoryRunRecorder(),
                      sleep=lambda _: None)
    orch = LegalOrchestrator(gateway=gw, classifier=RequestClassifier(gw, use_model=False),
                             retriever=lambda q, s: BAILMENT)
    return orch.run(message=message, roles=list(roles))


def test_prompt_tells_model_to_use_only_sources():
    assert NO_ANSWER_TOKEN in _GROUNDING
    assert "ONLY law you know" in _GROUNDING


def test_model_saying_no_answer_gives_no_answer_message():
    state = run(NO_ANSWER_TOKEN)
    assert state["answer"] == NO_ANSWER_MESSAGE
    assert state["citations"] == [] and state["reliable"] is False


def test_token_inside_longer_reply_still_gives_no_answer():
    state = run(f"Sorry.\n{NO_ANSWER_TOKEN}\nBut Section 302 IPC applies.")
    assert state["answer"] == NO_ANSWER_MESSAGE
    assert "302" not in state["answer"]


def test_answer_naming_law_not_in_sources_is_withheld():
    # The hallucination from the screenshot: IPC 302 / BNS 262 with only a bailment source.
    reply = ("Section 302, Indian Penal Code, 1860 deals with murder [1]. Under "
             "Section 262 of the Bharatiya Nyaya Sanhita, 2023 do not help him escape [1].")
    state = run(reply)
    assert state["answer"] == NO_ANSWER_MESSAGE
    assert "ungrounded_answer_blocked" in state["warnings"]
    assert "unsupported_provisions" in state["warnings"]
    assert state["citations"] == []


def test_answer_citing_no_source_is_withheld():
    state = run("He should get a good lawyer and stay calm.")
    assert state["answer"] == NO_ANSWER_MESSAGE
    assert "no_source_cited" in state["warnings"]


def test_grounded_answer_is_shown():
    reply = "Under Section 148 of the Indian Contract Act, 1872, a bailment is the delivery of goods for a purpose [1]."
    state = run(reply, message="What is bailment?")
    assert state["answer"].startswith("Under Section 148")
    assert state["citations"] and state["reliable"] is True


def test_drafts_are_not_blocked_but_still_flagged():
    reply = "LEGAL NOTICE\n1. Under Section 138 of the Negotiable Instruments Act ..."
    state = run(reply, message="Draft a legal notice for cheque bounce", roles=("LAWYER",))
    assert state["answer"].startswith("LEGAL NOTICE")
    assert "unsupported_provisions" in state["warnings"]
    assert state["reliable"] is False
