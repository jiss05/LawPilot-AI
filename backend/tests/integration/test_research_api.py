"""POST /api/v1/research/search through FastAPI, with real auth tokens and PostgreSQL."""

import pytest
from fastapi.testclient import TestClient

from app.api.research_routes import get_search_service
from app.core.security import create_access_token
from app.db.session import get_db
from app.main import app
from app.rag.store_retriever import LegalSearchService

from .helpers import ingest_statute, make_user


@pytest.fixture
def api(db, settings):
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_search_service] = lambda: LegalSearchService(settings)
    yield TestClient(app)
    app.dependency_overrides.clear()


def auth(user):
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def test_search_endpoint_returns_sources(api, db, settings):
    admin = make_user(db, "ADMIN")
    client_user = make_user(db, "CLIENT")
    ingest_statute(db, settings, admin)

    response = api.post(
        "/api/v1/research/search",
        json={"query": "penalty stipulated", "top_k": 3, "jurisdictions": ["India"]},
        headers=auth(client_user),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    top = body["results"][0]
    assert top["location"]["section_ref"] == "Section 74"
    assert top["source"]["source_title"] == "Sample Contract Act, 1872"
    assert top["source"]["citation"] == "Section 74, p. 3"
    assert top["source"]["version_label"] == "As amended 2023"
    assert set(top["channels"]) <= {"vector", "keyword"}
    assert body["degraded"] == []


def test_search_requires_login(api):
    assert api.post("/api/v1/research/search", json={"query": "compensation"}).status_code in (401, 403)


def test_search_validates_input(api, db):
    user = make_user(db, "CLIENT")
    response = api.post("/api/v1/research/search", json={"query": "x", "top_k": 500}, headers=auth(user))
    assert response.status_code == 422
