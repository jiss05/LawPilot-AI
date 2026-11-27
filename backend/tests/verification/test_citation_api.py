"""SCRUM-26: /api/v1/citations/verify uses the stored sources and hides private ones."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.main import app
from app.verification import store

CHUNK = uuid.uuid4()
PRIVATE = uuid.uuid4()
OWNER = uuid.uuid4()


def row(chunk_id, visibility="public", uploaded_by=None, section="Section 73"):
    return SimpleNamespace(
        chunk_id=chunk_id, text="the party who suffers by such breach is entitled to compensation",
        page_number=3, section_ref=section, title="Indian Contract Act", visibility=visibility,
        uploaded_by=uploaded_by, version_status="active", processing_status="completed",
    )


def user(role="CLIENT", user_id=None):
    return SimpleNamespace(id=user_id or uuid.uuid4(), is_active=True,
                           role_assignments=[SimpleNamespace(role=SimpleNamespace(code=role))])


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(store, "_hydrate", lambda db, ids: {
        CHUNK: row(CHUNK), PRIVATE: row(PRIVATE, visibility="private", uploaded_by=OWNER),
    })
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


def test_verify_endpoint_returns_statuses(client):
    app.dependency_overrides[get_current_user] = lambda: user()
    r = client.post("/api/v1/citations/verify", json={
        "text": "Compensation [1]. Something else [2].",
        "citations": [
            {"ref": 1, "chunk_id": str(CHUNK), "source_title": "Indian Contract Act"},
            {"ref": 2, "chunk_id": str(uuid.uuid4()), "source_title": "Invented Act"},
        ],
    })
    assert r.status_code == 200
    body = r.json()
    assert [c["verification_status"] for c in body["citations"]] == ["verified", "failed"]
    assert "source_not_found" in body["citations"][1]["verification_issues"]
    assert body["summary"]["verified"] is False
    assert "text" not in body["citations"][0]


def test_private_source_of_someone_else_is_treated_as_missing(client):
    app.dependency_overrides[get_current_user] = lambda: user()
    payload = {"text": "See [1].", "citations": [{"ref": 1, "chunk_id": str(PRIVATE)}]}
    r = client.post("/api/v1/citations/verify", json=payload)
    assert r.json()["citations"][0]["verification_issues"] == ["source_not_found"]

    app.dependency_overrides[get_current_user] = lambda: user(user_id=OWNER)
    r = client.post("/api/v1/citations/verify", json=payload)
    assert r.json()["citations"][0]["verification_status"] == "verified"
