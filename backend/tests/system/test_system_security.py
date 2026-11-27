"""
SCRUM-30: system and security tests.

Acceptance criteria covered here:
  * Authentication and role restrictions work correctly
  * Unauthorized document uploads are rejected
  * All three agent workflows are tested (client, lawyer, judge support) end to end
    through the HTTP API
  * Model and database failures are handled safely
Retrieval and citation verification are covered by tests/test_retriever.py,
tests/integration/*, tests/verification/* and tests/safety/*.
"""

from __future__ import annotations

import io
import json
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError

from app.api import admin_evaluation_routes, assistant_routes, knowledge_source_routes
from app.api.dependencies import get_current_user
from app.core.config import settings
from app.core.security import create_access_token
from app.db.session import get_db
from app.llm.config import ModelSettings
from app.llm.gateway import ModelGateway
from app.llm.providers.fake import FakeProvider
from app.llm.run_recorder import InMemoryRunRecorder
from app.llm.types import ModelUnavailableError
from app.main import INTERNAL_ERROR_MESSAGE, app
from app.orchestration.classifier import RequestClassifier
from app.orchestration.graph import LegalOrchestrator
from app.services import knowledge_source_service


def user(role, **extra):
    return SimpleNamespace(
        id=uuid.uuid4(), is_active=True, email_verified=True,
        role_assignments=[SimpleNamespace(role=SimpleNamespace(code=role))], **extra,
    )


@pytest.fixture(autouse=True)
def clean_overrides():
    yield
    app.dependency_overrides.clear()


@pytest.fixture
def client():
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


# =========================================================================== #
# Authentication
# =========================================================================== #
PROTECTED = [
    ("get", "/api/v1/users/me"),
    ("get", "/api/v1/assistant/agents"),
    ("post", "/api/v1/assistant/chat"),
    ("post", "/api/v1/assistant/feedback"),
    ("get", "/api/v1/drafts/"),
    ("post", "/api/v1/drafts/generate"),
    ("get", "/api/v1/matters"),
    ("post", "/api/v1/citations/verify"),
    ("post", "/api/v1/judge-support/case-brief"),
    ("get", "/api/v1/knowledge-sources"),
    ("post", "/api/v1/knowledge-sources"),
    ("get", "/api/v1/admin/ingestion-jobs/summary"),
    ("get", "/api/v1/admin/audit-events"),
    ("get", "/api/v1/admin/evaluation/reports"),
    ("get", "/api/v1/admin/feedback/summary"),
    ("post", "/api/v1/research/search"),
]


@pytest.mark.parametrize("method, path", PROTECTED)
def test_protected_endpoints_require_a_token(client, method, path):
    app.dependency_overrides[get_db] = lambda: None
    response = getattr(client, method)(path)
    assert response.status_code == 401, path
    assert response.headers.get("www-authenticate") == "Bearer"


class OneUserDB:
    def __init__(self, found):
        self.found = found

    def scalar(self, statement):
        return self.found


def _forged(sub, key="not-the-real-secret", minutes=10):
    return jwt.encode(
        {"sub": sub, "exp": datetime.now(timezone.utc) + timedelta(minutes=minutes)},
        key, algorithm=settings.JWT_ALGORITHM,
    )


@pytest.mark.parametrize("token", [
    "not-a-jwt",
    _forged(str(uuid.uuid4())),                                   # wrong signing key
    create_access_token(str(uuid.uuid4()), expires_delta=timedelta(seconds=-5)),  # expired
    create_access_token("not-a-uuid"),                            # bad subject
    jwt.encode({"sub": str(uuid.uuid4())}, None, algorithm="none"),  # unsigned "alg: none"
])
def test_invalid_tokens_are_rejected(client, token):
    app.dependency_overrides[get_db] = lambda: OneUserDB(user("ADMIN"))
    r = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


@pytest.mark.parametrize("found", [
    None,                                  # deleted user
    SimpleNamespace(**{**vars(user("CLIENT")), "is_active": False}),       # deactivated
    SimpleNamespace(**{**vars(user("CLIENT")), "email_verified": False}),  # email not verified
])
def test_valid_token_for_unusable_account_is_rejected(client, found):
    app.dependency_overrides[get_db] = lambda: OneUserDB(found)
    token = create_access_token(str(uuid.uuid4()))
    r = client.get("/api/v1/users/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 401


# =========================================================================== #
# Role restrictions
# =========================================================================== #
ROLE_DENIED = [
    # (method, path, json, roles that must be refused)
    ("get", "/api/v1/admin/ingestion-jobs/summary", None, ["CLIENT", "LAWYER", "JUDGE"]),
    ("get", "/api/v1/admin/audit-events", None, ["CLIENT", "LAWYER", "JUDGE"]),
    ("get", "/api/v1/admin/evaluation/reports", None, ["CLIENT", "LAWYER", "JUDGE"]),
    ("get", "/api/v1/admin/evaluation/runtime", None, ["CLIENT", "LAWYER", "JUDGE"]),
    ("get", "/api/v1/admin/feedback/summary", None, ["CLIENT", "LAWYER", "JUDGE"]),
    ("get", "/api/v1/admin/dashboard", None, ["CLIENT", "LAWYER", "JUDGE"]),
    ("post", "/api/v1/matters", {"title": "X"}, ["CLIENT", "JUDGE", "ADMIN"]),
    ("post", "/api/v1/drafts/generate", {"matter_id": str(uuid.uuid4()), "title": "T",
                                          "document_type": "Notice", "case_facts": "x" * 30},
     ["CLIENT", "JUDGE", "ADMIN"]),
    ("post", "/api/v1/judge-support/case-brief", {
        "case_title": "X", "facts": [{"text": "abc", "source_ref": "P1"}],
        "parties": [{"name": "A", "role": "P", "arguments": [{"text": "abc"}]},
                    {"name": "B", "role": "R", "arguments": [{"text": "abc"}]}],
    }, ["CLIENT", "LAWYER"]),
]


@pytest.mark.parametrize("method, path, body, roles", ROLE_DENIED)
def test_roles_without_permission_get_403(client, method, path, body, roles):
    app.dependency_overrides[get_db] = lambda: None
    for role in roles:
        app.dependency_overrides[get_current_user] = lambda role=role: user(role)
        kwargs = {"json": body} if body is not None else {}
        r = getattr(client, method)(path, **kwargs)
        assert r.status_code == 403, f"{role} reached {path}"


# =========================================================================== #
# Document uploads
# =========================================================================== #
def _upload(client, filename="act.pdf", content=b"%PDF-1.7 test", content_type="application/pdf"):
    return client.post(
        "/api/v1/knowledge-sources",
        data={"title": "Test Act", "source_type": "statute", "jurisdiction": "India", "trust_tier": "primary"},
        files={"file": (filename, io.BytesIO(content), content_type)},
    )


@pytest.mark.parametrize("role", ["CLIENT", "LAWYER", "JUDGE"])
def test_non_admin_upload_is_rejected(client, role):
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: user(role)
    assert _upload(client).status_code == 403


def test_unauthenticated_upload_is_rejected(client):
    app.dependency_overrides[get_db] = lambda: None
    assert _upload(client).status_code == 401


@pytest.mark.parametrize("filename, content, content_type", [
    ("malware.exe", b"MZ\x90\x00", "application/octet-stream"),
    ("notes.docx", b"PK\x03\x04", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ("act.pdf", b"%PDF-1.7", "text/html"),
])
def test_admin_upload_of_wrong_file_type_is_rejected(client, filename, content, content_type):
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: user("ADMIN")
    r = _upload(client, filename, content, content_type)
    assert r.status_code == 400


def test_admin_upload_of_fake_pdf_is_rejected(client, monkeypatch):
    """A file named .pdf whose bytes are not a PDF is refused by the content check."""
    def register(db, *, file_content, **kw):
        knowledge_source_service._validate_pdf(file_content)
        raise AssertionError("should have been rejected")

    monkeypatch.setattr(knowledge_source_routes, "register_legal_source", register)
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: user("ADMIN")
    r = _upload(client, "judgment.pdf", b"<html><script>alert(1)</script></html>")
    assert r.status_code == 400


# =========================================================================== #
# The three agent workflows, end to end through the API
# =========================================================================== #
class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def flush(self):
        pass

    def commit(self):
        pass

    def rollback(self):
        pass


SOURCES = [{
    "chunk_id": "chunk-1", "source_title": "Negotiable Instruments Act, 1881",
    "text": "Section 138. Dishonour of cheque for insufficiency of funds in the account.",
    "citation": "Section 138", "section_ref": "Section 138", "url": None,
}]


@pytest.fixture
def chat(monkeypatch):
    def make(replies):
        gw = ModelGateway(ModelSettings(provider="fake", max_retries=0, retry_backoff_seconds=0),
                          provider=FakeProvider(replies), recorder=InMemoryRunRecorder(),
                          sleep=lambda _: None)
        orch = LegalOrchestrator(gateway=gw, classifier=RequestClassifier(gw, use_model=False))
        app.dependency_overrides[assistant_routes.get_orchestrator] = lambda: orch
        app.dependency_overrides[get_db] = lambda: FakeSession()
        monkeypatch.setattr(assistant_routes, "_make_retriever", lambda db, u: lambda q, s: SOURCES)
        return gw
    return make


@pytest.mark.parametrize("role, message, agent", [
    ("CLIENT", "Can my cheque bounce lead to a criminal case?", "client"),
    ("LAWYER", "Find case law on Section 138 of the NI Act", "lawyer"),
    ("JUDGE", "List the issues for determination in this cheque bounce case", "judge_support"),
])
def test_agent_workflow_end_to_end(client, chat, role, message, agent):
    chat(["Dishonour of a cheque is an offence under Section 138 [1]."])
    app.dependency_overrides[get_current_user] = lambda: user(role)
    r = client.post("/api/v1/assistant/chat", json={"message": message})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answered_by"] == agent
    assert body["status"] == "completed"
    assert body["reliable"] is True
    assert body["citations"][0]["verification_status"] == "verified"
    assert body["message_id"]


@pytest.mark.parametrize("role, agent", [
    ("CLIENT", "lawyer"), ("CLIENT", "judge_support"),
    ("JUDGE", "lawyer"), ("JUDGE", "client"),
    ("LAWYER", "judge_support"),
])
def test_agent_not_permitted_for_role_is_403(client, chat, role, agent):
    chat(["unused"])
    app.dependency_overrides[get_current_user] = lambda: user(role)
    r = client.post("/api/v1/assistant/chat", json={"message": "Explain bail", "agent": agent})
    assert r.status_code == 403


def test_agents_list_matches_role(client, chat):
    chat([])
    app.dependency_overrides[get_current_user] = lambda: user("JUDGE")
    names = [a["name"] for a in client.get("/api/v1/assistant/agents").json()["agents"]]
    assert names == ["judge_support"]


# =========================================================================== #
# Model and database failures
# =========================================================================== #
def test_model_outage_returns_understandable_unreliable_answer(client, chat):
    chat([ModelUnavailableError("connection refused http://admin:s3cret@ollama:11434")])
    app.dependency_overrides[get_current_user] = lambda: user("CLIENT")
    r = client.post("/api/v1/assistant/chat", json={"message": "Explain anticipatory bail"})
    assert r.status_code == 200
    body = r.json()
    assert body["reliable"] is False
    assert "temporarily unavailable" in body["answer"]
    assert "s3cret" not in r.text


class BrokenDB:
    def _fail(self, *a, **k):
        raise OperationalError("SELECT 1", {}, Exception(
            "could not connect to server: postgresql://lawpilot:hunter22@10.0.0.5:5432/lawpilot"))

    scalar = scalars = execute = get = _fail

    def rollback(self):
        pass


def test_database_outage_hides_details(client):
    app.dependency_overrides[get_db] = lambda: BrokenDB()
    app.dependency_overrides[get_current_user] = lambda: user("LAWYER")
    r = client.get("/api/v1/matters")
    assert r.status_code == 500
    assert r.json()["detail"] == INTERNAL_ERROR_MESSAGE
    for leak in ("hunter22", "OperationalError", "Traceback", "10.0.0.5", "postgresql://"):
        assert leak not in r.text


def test_chat_survives_database_outage_when_saving(client, chat):
    chat(["Dishonour is an offence [1]."])
    app.dependency_overrides[get_db] = lambda: BrokenDB()
    BrokenDB.add = BrokenDB._fail
    app.dependency_overrides[get_current_user] = lambda: user("CLIENT")
    r = client.post("/api/v1/assistant/chat", json={"message": "Can a cheque bounce be a crime?"})
    assert r.status_code == 200
    assert "conversation_not_saved" in r.json()["warnings"]


# =========================================================================== #
# SCRUM-29 endpoints: evaluation reports and feedback
# =========================================================================== #
def test_evaluation_reports_are_listed_newest_first(client, tmp_path, monkeypatch):
    for stamp, passed in (("20261124-181057", False), ("20261124-184950", True)):
        (tmp_path / f"qwen-{stamp}.json").write_text(json.dumps({
            "provider": "ollama", "model": "qwen", "passed": passed,
            "criteria": {"min_content_pass_rate": 0.7},
            "metrics": {"availability": 1.0, "content_pass_rate": 0.75},
            "checks": {"content": True}, "cases": [{"id": "a", "passed": True}, {"id": "b", "passed": False}],
        }))
    (tmp_path / "broken.json").write_text("{not json")
    monkeypatch.setattr(admin_evaluation_routes, "REPORTS_DIR", tmp_path)
    app.dependency_overrides[get_current_user] = lambda: user("ADMIN")

    reports = client.get("/api/v1/admin/evaluation/reports").json()
    assert [r["passed"] for r in reports] == [True, False]
    assert reports[0]["cases_passed"] == 1 and reports[0]["cases_total"] == 2

    detail = client.get(f"/api/v1/admin/evaluation/reports/{reports[0]['name']}").json()
    assert len(detail["cases"]) == 2


@pytest.mark.parametrize("name", ["..%2F..%2F.env", "../secrets.json", "x.txt", "%2Fetc%2Fpasswd"])
def test_report_path_traversal_is_refused(client, tmp_path, monkeypatch, name):
    monkeypatch.setattr(admin_evaluation_routes, "REPORTS_DIR", tmp_path)
    app.dependency_overrides[get_current_user] = lambda: user("ADMIN")
    assert client.get(f"/api/v1/admin/evaluation/reports/{name}").status_code == 404


class FeedbackDB(FakeSession):
    def __init__(self, message):
        super().__init__()
        self.message = message

    def scalar(self, statement):
        return self.message


def test_user_can_rate_own_answer(client):
    msg = SimpleNamespace(id=uuid.uuid4())
    db = FeedbackDB(msg)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_current_user] = lambda: user("CLIENT")
    r = client.post("/api/v1/assistant/feedback",
                    json={"message_id": str(msg.id), "rating": 2, "issue_type": "unsupported_citation"})
    assert r.status_code == 201
    assert db.added[0].rating == 2


def test_cannot_rate_someone_elses_answer(client):
    app.dependency_overrides[get_db] = lambda: FeedbackDB(None)
    app.dependency_overrides[get_current_user] = lambda: user("CLIENT")
    r = client.post("/api/v1/assistant/feedback", json={"message_id": str(uuid.uuid4()), "rating": 5})
    assert r.status_code == 404


@pytest.mark.parametrize("rating", [0, 6])
def test_rating_out_of_range_is_rejected(client, rating):
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_current_user] = lambda: user("CLIENT")
    r = client.post("/api/v1/assistant/feedback", json={"message_id": str(uuid.uuid4()), "rating": rating})
    assert r.status_code == 422
