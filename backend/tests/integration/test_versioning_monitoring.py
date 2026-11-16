"""
SCRUM-18 acceptance criteria (real PostgreSQL + embedded Qdrant + FastAPI):
  * Source versions are maintained.
  * Previous versions are preserved.
  * Ingestion status is recorded.
  * Processing failures are visible.
  * Administrative operations are traceable.
"""

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.research_routes import get_search_service
from app.core.security import create_access_token
from app.db.session import get_db
from app.ingestion import config as ingestion_config
from app.ingestion.vector_store import QdrantVectorStore
from app.main import app
from app.models.audit_event import AuditEvent
from app.models.document_chunk import DocumentChunk
from app.models.ingestion_job import IngestionJob
from app.models.source_version import SourceVersion
from app.rag.store_retriever import LegalSearchService, access_context_for

from .helpers import ingest_statute, make_user

AMENDMENT = "75. Interest on delayed payment. - Where payment under a contract is delayed, interest is payable at the notified rate."


@pytest.fixture
def admin(db):
    return make_user(db, "ADMIN")


@pytest.fixture
def api(db, settings, monkeypatch):
    # Configure the WHOLE app with the test settings the same way production
    # is configured: INGESTION_* environment variables (embedded Qdrant,
    # hashing embeddings, temporary folders).
    for field, value in {
        "storage_dir": settings.storage_dir, "extracted_dir": settings.extracted_dir,
        "ocr_enabled": "false", "embedding_provider": "hashing",
        "embedding_dimension": settings.embedding_dimension,
        "qdrant_url": settings.qdrant_url, "qdrant_collection": settings.qdrant_collection,
    }.items():
        monkeypatch.setenv(f"INGESTION_{field.upper()}", str(value))
    ingestion_config.get_ingestion_settings.cache_clear()
    # Background tasks would open their own DB session; run nothing in the background here.
    monkeypatch.setattr("app.api.knowledge_source_routes.process_uploaded_document", lambda *a: None)
    monkeypatch.setattr("app.api.admin_ingestion_routes.process_uploaded_document", lambda *a: None)
    app.dependency_overrides[get_db] = lambda: db
    app.dependency_overrides[get_search_service] = lambda: LegalSearchService(settings)
    yield TestClient(app)
    app.dependency_overrides.clear()
    ingestion_config.get_ingestion_settings.cache_clear()


def auth(user):
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


def search_texts(db, settings, user, query):
    response = LegalSearchService(settings).search(db, query, access=access_context_for(user), top_k=20)
    return [r.text for r in response.results]


# --------------------------------------------------------------------------
# Versions maintained / previous versions preserved
# --------------------------------------------------------------------------
def test_new_edition_supersedes_old_one_and_old_one_is_preserved(db, settings, admin):
    source, v1, doc1 = ingest_statute(db, settings, admin, version_label="2023")
    assert v1.status == "active" and doc1.processing_status == "completed"

    _, v2, doc2 = ingest_statute(db, settings, admin, source=source, version_label="2024", amendment=AMENDMENT)
    db.refresh(v1)
    assert v2.status == "active"
    assert v1.status == "superseded"                        # replaced ...
    assert v2.supersedes_version_id == v1.id                # ... and linked in the history chain

    # Preserved: the old edition's chunks and vectors still exist.
    old_chunks = db.scalar(select(func.count()).select_from(DocumentChunk)
                           .where(DocumentChunk.knowledge_document_id == doc1.id))
    assert old_chunks > 0
    assert QdrantVectorStore(settings).count_document(doc1.id) == old_chunks

    # Search only uses the active edition.
    client_user = make_user(db, "CLIENT")
    texts = search_texts(db, settings, client_user, "interest on delayed payment")
    assert any("Interest on delayed payment" in t for t in texts)
    results = LegalSearchService(settings).search(db, "penalty stipulated", access=access_context_for(client_user))
    assert {r.source.document_id for r in results.results} == {doc2.id}


def test_admin_can_roll_back_to_previous_edition(api, db, settings, admin):
    source, v1, _ = ingest_statute(db, settings, admin, version_label="2023")
    _, v2, _ = ingest_statute(db, settings, admin, source=source, version_label="2024", amendment=AMENDMENT)

    response = api.post(f"/api/v1/knowledge-sources/{source.id}/versions/{v1.id}/activate",
                        json={"reason": "2024 amendment stayed by court"}, headers=auth(admin))
    assert response.status_code == 200, response.text
    assert response.json()["version"]["status"] == "active"
    assert response.json()["superseded_version_ids"] == [str(v2.id)]
    db.refresh(v2)
    assert v2.status == "superseded"

    history = api.get(f"/api/v1/knowledge-sources/{source.id}/versions", headers=auth(admin)).json()
    assert {v["version_label"]: v["status"] for v in history} == {"2024": "superseded", "2023": "active"}
    assert all(v["documents"][0]["chunk_count"] > 0 for v in history)


def test_withdrawn_edition_disappears_from_search_but_is_kept(api, db, settings, admin):
    source, v1, doc = ingest_statute(db, settings, admin)
    client_user = make_user(db, "CLIENT")
    assert search_texts(db, settings, client_user, "penalty stipulated")

    response = api.post(f"/api/v1/knowledge-sources/{source.id}/versions/{v1.id}/withdraw",
                        json={"reason": "published in error"}, headers=auth(admin))
    assert response.status_code == 200
    assert response.json()["version"]["status"] == "withdrawn"
    assert search_texts(db, settings, client_user, "penalty stipulated") == []
    assert db.get(SourceVersion, v1.id) is not None  # nothing deleted


def test_uploading_a_new_edition_through_the_api(api, db, settings, admin, tmp_path):
    from tests.ingestion.helpers import make_statute_pdf

    source, *_ = ingest_statute(db, settings, admin)
    pdf = make_statute_pdf(tmp_path / "v2.pdf", AMENDMENT).read_bytes()
    response = api.post(
        f"/api/v1/knowledge-sources/{source.id}/versions",
        data={"version_label": "2024", "published_at": "2024-04-01"},
        files={"file": ("act_2024.pdf", pdf, "application/pdf")},
        headers=auth(admin),
    )
    assert response.status_code == 201, response.text
    assert response.json()["status"] == "pending"   # active edition untouched until processed

    duplicate = api.post(
        f"/api/v1/knowledge-sources/{source.id}/versions",
        data={"version_label": "again"},
        files={"file": ("act_2024.pdf", pdf, "application/pdf")},
        headers=auth(admin),
    )
    assert duplicate.status_code == 400
    assert "already registered" in duplicate.json()["detail"]


def test_only_admins_manage_versions_and_monitoring(api, db, settings, admin):
    source, v1, doc = ingest_statute(db, settings, admin)
    lawyer = make_user(db, "LAWYER")
    for method, url in [
        ("get", f"/api/v1/knowledge-sources/{source.id}/versions"),
        ("post", f"/api/v1/knowledge-sources/{source.id}/versions/{v1.id}/withdraw"),
        ("get", "/api/v1/admin/ingestion-jobs"),
        ("get", "/api/v1/admin/ingestion-jobs/summary"),
        ("get", f"/api/v1/admin/documents/{doc.id}/status"),
        ("get", "/api/v1/admin/audit-events"),
    ]:
        extra = {"json": {"reason": "not allowed"}} if method == "post" else {}
        response = getattr(api, method)(url, headers=auth(lawyer), **extra)
        assert response.status_code == 403, url


# --------------------------------------------------------------------------
# Ingestion status recorded / failures visible
# --------------------------------------------------------------------------
def test_every_stage_is_recorded_and_visible(api, db, settings, admin):
    _, version, doc = ingest_statute(db, settings, admin)
    body = api.get(f"/api/v1/admin/documents/{doc.id}/status", headers=auth(admin)).json()
    assert [j["stage"] for j in body["jobs"]] == ["text_extraction", "chunking", "indexing", "activation"]
    assert all(j["status"] == "completed" for j in body["jobs"])
    assert body["searchable"] is True
    assert body["chunk_count"] == body["vector_count"] > 0

    jobs = api.get(f"/api/v1/admin/ingestion-jobs?document_id={doc.id}&stage=indexing", headers=auth(admin)).json()
    assert jobs["total"] == 1 and jobs["items"][0]["counts"]["vectors"] == body["chunk_count"]


def test_failures_are_visible(api, db, settings, admin, tmp_path):
    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"%PDF-1.7\n" + b"\x00garbage" * 50)
    from app.ingestion.tasks import process_document
    from app.models.knowledge_document import KnowledgeDocument
    from app.models.knowledge_source import KnowledgeSource

    source = KnowledgeSource(title="Broken Act", source_type="statute", jurisdiction="India", trust_tier="official")
    db.add(source); db.flush()
    version = SourceVersion(source_id=source.id, content_hash=uuid.uuid4().hex, status="pending")
    db.add(version); db.flush()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    doc_id = uuid.uuid4()
    (settings.storage_dir / f"{doc_id}.pdf").write_bytes(broken.read_bytes())
    doc = KnowledgeDocument(id=doc_id, source_version_id=version.id, filename="broken.pdf",
                            file_type="application/pdf", storage_key=f"{doc_id}.pdf", sha256="",
                            uploaded_by=admin.id, processing_status="pending", visibility="public")
    db.add(doc); db.commit()

    process_document(db, doc.id, admin.id)  # uses the patched settings
    db.refresh(version)
    assert version.status == "failed"

    failed = api.get("/api/v1/admin/ingestion-jobs?status=failed", headers=auth(admin)).json()
    assert any(j["knowledge_document_id"] == str(doc.id) and j["error_code"] == "CORRUPTED_FILE"
               for j in failed["items"])
    summary = api.get("/api/v1/admin/ingestion-jobs/summary", headers=auth(admin)).json()
    assert summary["failures_last_24h_by_code"].get("CORRUPTED_FILE", 0) >= 1
    assert any(f["document_id"] == str(doc.id) and f["last_error"].startswith("[CORRUPTED_FILE]")
               for f in summary["failed_documents"])
    assert summary["vector_store"]["status"] == "ok"


def test_reprocess_is_audited_and_blocked_while_running(api, db, settings, admin):
    _, _, doc = ingest_statute(db, settings, admin)
    response = api.post("/api/v1/admin/ingestion-jobs", json={"document_id": str(doc.id)},
                        headers={**auth(admin), "X-Request-ID": "demo-req-42"})
    assert response.status_code == 202
    assert response.headers["X-Request-ID"] == "demo-req-42"

    doc.processing_status = "chunking"
    db.commit()
    busy = api.post("/api/v1/admin/ingestion-jobs", json={"document_id": str(doc.id)}, headers=auth(admin))
    assert busy.status_code == 409


# --------------------------------------------------------------------------
# Administrative operations traceable
# --------------------------------------------------------------------------
def test_admin_actions_are_in_the_audit_trail(api, db, settings, admin):
    source, v1, doc = ingest_statute(db, settings, admin)
    _, v2, _ = ingest_statute(db, settings, admin, source=source, version_label="2024", amendment=AMENDMENT)
    api.post(f"/api/v1/knowledge-sources/{source.id}/versions/{v2.id}/withdraw",
             json={"reason": "typo in gazette"}, headers={**auth(admin), "X-Request-ID": "req-withdraw-1"})

    events = api.get("/api/v1/admin/audit-events?limit=50", headers=auth(admin)).json()["items"]
    actions = [e["action"] for e in events]
    assert "source_version.activated" in actions
    assert "source_version.superseded" in actions
    withdrawn = next(e for e in events if e["action"] == "source_version.withdrawn")
    assert withdrawn["target_id"] == str(v2.id)
    assert withdrawn["actor_email"] == admin.email
    assert withdrawn["request_id"] == "req-withdraw-1"
    assert withdrawn["metadata"]["reason"] == "typo in gazette"

    by_target = api.get(f"/api/v1/admin/audit-events?target_id={v1.id}", headers=auth(admin)).json()
    assert {e["action"] for e in by_target["items"]} == {"source_version.activated", "source_version.superseded"}


def test_upload_through_api_is_audited(api, db, settings, admin, tmp_path):
    from tests.ingestion.helpers import make_statute_pdf

    pdf = make_statute_pdf(tmp_path / "act.pdf").read_bytes()
    response = api.post(
        "/api/v1/knowledge-sources",
        data={"title": "Audited Act", "source_type": "statute", "jurisdiction": "India", "trust_tier": "official"},
        files={"file": ("act.pdf", pdf, "application/pdf")},
        headers={**auth(admin), "X-Request-ID": "upload-7"},
    )
    assert response.status_code == 201, response.text
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "knowledge_source.created",
                                               AuditEvent.target_id == response.json()["id"]))
    assert event is not None and event.request_id == "upload-7" and event.actor_user_id == admin.id
    jobs = db.scalar(select(func.count()).select_from(IngestionJob))
    assert jobs is not None
