"""SCRUM-27: safe response handling."""

import logging
import uuid
from types import SimpleNamespace

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app.llm.config import ModelSettings
from app.llm.gateway import ModelGateway
from app.llm.providers.fake import FakeProvider
from app.llm.run_recorder import InMemoryRunRecorder
from app.llm.types import ModelUnavailableError
from app.main import INTERNAL_ERROR_MESSAGE, app
from app.orchestration.classifier import RequestClassifier
from app.orchestration.graph import LegalOrchestrator
from app.safety.redaction import RedactingFilter, redact_secrets
from app.safety.responses import assess_reliability, detect_conflicts


def gateway(replies=None):
    s = ModelSettings(provider="fake", max_retries=0, retry_backoff_seconds=0)
    return ModelGateway(s, provider=FakeProvider(replies), recorder=InMemoryRunRecorder(), sleep=lambda _: None)


def run(replies, sources, message="Explain compensation for breach of contract", roles=("LAWYER",)):
    gw = gateway(replies)
    orch = LegalOrchestrator(gateway=gw, classifier=RequestClassifier(gw, use_model=False),
                             retriever=lambda q, s: sources)
    return orch.run(message=message, roles=list(roles))


S73 = {"chunk_id": "c1", "text": "Section 73. The party who suffers by such breach is entitled to compensation.",
       "source_title": "Indian Contract Act", "citation": "Section 73", "section_ref": "Section 73"}
S73_OLD = {"chunk_id": "c2", "text": "Section 73. No compensation is payable for remote or indirect loss "
           "sustained by reason of the breach, and penalties are fixed by schedule.",
           "source_title": "Indian Contract Act", "citation": "Section 73", "section_ref": "Section 73"}


# ------------------------------------------------------------------ reliability
def test_supported_verified_answer_is_reliable():
    state = run(["Compensation is available [1]."], [S73])
    assert state["status"] == "completed"
    assert state["reliable"] is True
    assert state["notice"] is None
    assert state["citations"][0]["verification_status"] == "verified"


def test_unsupported_question_is_not_presented_as_reliable():
    state = run([], [S73], message="Give me a biryani recipe", roles=("CLIENT",))
    assert state["status"] == "rejected"
    assert state["reliable"] is False
    assert "outside" in state["notice"]


def test_no_evidence_answer_is_not_reliable():
    state = run(["should not be called"], [])
    assert state["reliable"] is False
    assert "No supporting legal source" in state["notice"]


def test_failed_citation_makes_answer_unreliable():
    state = run(['The Act states "damages are always tripled" [1] and see [4].'], [S73])
    assert state["reliable"] is False
    assert "citation_verification_failed" in state["warnings"]
    assert state["citations"][0]["verification_status"] == "failed"
    assert state["verification"]["invalid_references"] == [4]
    assert "could not be verified" in state["notice"]


def test_model_failure_gives_understandable_unreliable_message():
    state = run([ModelUnavailableError("connection refused to http://user:pw@ollama:11434")], [S73])
    assert state["reliable"] is False
    assert "temporarily unavailable" in state["answer"]
    assert "pw" not in state["answer"] and "Traceback" not in state["answer"]


# ------------------------------------------------------------------ conflicts
def test_conflicting_sources_are_identified():
    conflicts = detect_conflicts([S73, S73_OLD])
    assert len(conflicts) == 1
    assert conflicts[0]["refs"] == [1, 2]
    assert conflicts[0]["provision"] == "section 73"


def test_same_text_or_different_provisions_do_not_conflict():
    assert detect_conflicts([S73, dict(S73, chunk_id="c3")]) == []
    other = dict(S73_OLD, section_ref="Section 74", citation="Section 74")
    assert detect_conflicts([S73, other]) == []


def test_orchestrator_reports_conflict_in_answer():
    state = run(["Compensation is available [1], but see [2]."], [S73, S73_OLD])
    assert state["conflicts"]
    assert "Conflicting sources" in state["answer"]
    assert "conflicting_sources" in state["warnings"]
    assert state["reliable"] is False


def test_assess_reliability_failed_status():
    r = assess_reliability(status="failed", citations=[], verification=None, conflicts=[])
    assert r.reliable is False and r.notice


# ------------------------------------------------------------------ secrets
@pytest.mark.parametrize("raw, secret", [
    ("postgresql://lawpilot:SuperSecret1@db:5432/app", "SuperSecret1"),
    ("Authorization: Bearer abcdefghijklmnop123", "abcdefghijklmnop123"),
    ("token eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.c2lnbmF0dXJlX2hlcmU", "eyJzdWIiOiIxMjMifQ"),
    ("JWT_SECRET_KEY=my-jwt-secret-value", "my-jwt-secret-value"),
    ('{"password": "hunter22"}', "hunter22"),
    ("key sk-ant-abcdefghijklmnopqrstuv", "sk-ant-abcdefghijklmnopqrstuv"),
])
def test_secrets_are_redacted(raw, secret):
    out = redact_secrets(raw)
    assert secret not in out
    assert "[REDACTED]" in out


def test_ordinary_text_is_unchanged():
    text = "Section 73 of the Indian Contract Act deals with compensation."
    assert redact_secrets(text) == text


def test_log_filter_redacts():
    record = logging.LogRecord("x", logging.ERROR, __file__, 1, "db url %s", ("postgresql://u:pw123@h/db",), None)
    RedactingFilter().filter(record)
    assert "pw123" not in record.getMessage()


# ------------------------------------------------------------------ HTTP errors
_boom = APIRouter()


@_boom.get("/__test__/boom")
def _boom_route():
    raise RuntimeError("database password=hunter22 at postgresql://u:hunter22@db/app")


app.include_router(_boom)


def test_unhandled_error_hides_stack_trace_and_secrets():
    with TestClient(app, raise_server_exceptions=False) as client:
        r = client.get("/__test__/boom", headers={"X-Request-ID": "req-123"})
    assert r.status_code == 500
    body = r.json()
    assert body["detail"] == INTERNAL_ERROR_MESSAGE
    assert body["request_id"] == "req-123"
    assert "hunter22" not in r.text and "Traceback" not in r.text and "RuntimeError" not in r.text
    assert r.headers.get("X-Request-ID") == "req-123"


def test_validation_errors_do_not_echo_submitted_values():
    with TestClient(app) as client:
        r = client.post("/api/v1/auth/login", json={"email": "not-an-email", "password": 12345678901})
    assert r.status_code == 422
    assert "12345678901" not in r.text
    assert all({"loc", "msg", "type"} >= set(e) for e in r.json()["detail"])
