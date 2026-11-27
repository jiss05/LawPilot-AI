"""SCRUM-21: /api/v1/assistant endpoints (no database, fake model)."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import assistant_routes
from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.llm.config import ModelSettings
from app.llm.gateway import ModelGateway
from app.llm.providers.fake import FakeProvider
from app.llm.run_recorder import InMemoryRunRecorder
from app.main import app
from app.orchestration.classifier import RequestClassifier
from app.orchestration.graph import LegalOrchestrator


def user(*roles):
    return SimpleNamespace(id=uuid.uuid4(), is_active=True,
                           role_assignments=[SimpleNamespace(role=SimpleNamespace(code=r)) for r in roles])


class FakeSession:
    """Accepts the conversation/message writes the route makes."""

    def __init__(self):
        self.added = []

    def add(self, obj):
        if getattr(obj, "id", None) is None and hasattr(obj, "owner_user_id"):
            obj.id = uuid.uuid4()
        self.added.append(obj)

    def flush(self):
        for obj in self.added:
            if getattr(obj, "id", None) is None and hasattr(obj, "owner_user_id"):
                obj.id = uuid.uuid4()

    def commit(self):
        pass

    def rollback(self):
        pass


@pytest.fixture
def setup(monkeypatch):
    session = FakeSession()
    gw = ModelGateway(ModelSettings(provider="fake"), provider=FakeProvider(["Model answer [1]"]),
                      recorder=InMemoryRunRecorder())
    orch = LegalOrchestrator(gateway=gw, classifier=RequestClassifier(gw, use_model=False))
    monkeypatch.setattr(
        assistant_routes,
        "_make_retriever",
        lambda db, current_user: lambda query, state: [
            {
                "chunk_id": "test-source-1",
                "text": "Relevant legal provisions for testing.",
                "source_title": "Test Legal Authority",
                "citation": "Test citation",
                "url": None,
            }
        ],
    )
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[assistant_routes.get_orchestrator] = lambda: orch

    def as_user(u):
        app.dependency_overrides[get_current_user] = lambda: u

    with TestClient(app) as client:
        yield client, as_user, session
    app.dependency_overrides.clear()


def test_requires_login(setup):
    client, _, _ = setup
    app.dependency_overrides.pop(get_current_user, None)
    assert client.post("/api/v1/assistant/chat", json={"message": "hi"}).status_code == 401


def test_list_agents_by_role(setup):
    client, as_user, _ = setup
    as_user(user("LAWYER"))
    body = client.get("/api/v1/assistant/agents").json()
    assert body["roles"] == ["LAWYER"]
    assert {a["name"] for a in body["agents"]} == {"lawyer", "client"}


def test_chat_answers_and_saves_conversation(setup):
    client, as_user, session = setup
    as_user(user("CLIENT"))
    r = client.post("/api/v1/assistant/chat",
                    json={"message": "Can my landlord evict me?", "use_knowledge_base": True},
                    headers={"X-Request-ID": "abc-123"})
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "Model answer [1]" and body["answered_by"] == "client"
    assert body["status"] == "completed" and body["request_id"] == "abc-123"
    assert body["conversation_id"] is not None
    kinds = [type(o).__name__ for o in session.added]
    assert kinds == ["Conversation", "Message", "Message"]
    assert session.added[2].sender_type == "assistant" and session.added[2].model_run_id is not None


def test_forbidden_agent_returns_403(setup):
    client, as_user, _ = setup
    as_user(user("CLIENT"))
    r = client.post("/api/v1/assistant/chat", json={"message": "Explain bail", "agent": "judge_support"})
    assert r.status_code == 403


def test_saving_failure_still_returns_answer(setup):
    client, as_user, session = setup
    as_user(user("CLIENT"))
    session.commit = lambda: (_ for _ in ()).throw(RuntimeError("db down"))
    body = client.post("/api/v1/assistant/chat",
                       json={"message": "Explain bail", "use_knowledge_base": True}).json()
    assert body["answer"] == "Model answer [1]"
    assert "conversation_not_saved" in body["warnings"]
