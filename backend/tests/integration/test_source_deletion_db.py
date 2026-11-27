"""
Deleting a legal source removes everything (real PostgreSQL + embedded Qdrant).
Runs only with TEST_DATABASE_URL (see conftest.py); rolled back afterwards.
"""

import uuid

import pytest
from sqlalchemy import func, select

from app.ingestion.storage import extraction_output_path
from app.ingestion.vector_store import QdrantVectorStore
from app.models.audit_event import AuditEvent
from app.models.document_chunk import DocumentChunk
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_source import KnowledgeSource
from app.models.source_version import SourceVersion
from app.services.source_deletion import delete_legal_source

from .helpers import ingest_statute, make_user

AMENDMENT = "75. Interest on delayed payment. - Interest is payable at the notified rate."


def count(db, model, *where):
    return db.scalar(select(func.count()).select_from(model).where(*where))


def test_delete_removes_rows_vectors_and_files(db, settings):
    admin = make_user(db, "ADMIN")
    source, v1, d1 = ingest_statute(db, settings, admin)
    _, v2, d2 = ingest_statute(db, settings, admin, source=source, version_label="2024", amendment=AMENDMENT)
    keep_source, _, keep_doc = ingest_statute(db, settings, admin, title=f"Other Act {uuid.uuid4().hex[:6]}")

    store = QdrantVectorStore(settings)
    docs = [d1, d2]
    assert all(store.count_document(d.id) > 0 for d in docs)
    assert count(db, DocumentChunk, DocumentChunk.knowledge_document_id.in_([d.id for d in docs])) > 0
    files = [settings.storage_dir / d.storage_key for d in docs] + [extraction_output_path(d.id, settings) for d in docs]
    assert all(f.exists() for f in files)

    result = delete_legal_source(db, source.id, actor_user_id=admin.id, settings=settings, vector_store=store)

    assert (result.versions, result.documents) == (2, 2)
    assert result.chunks > 0 and result.files_deleted == 4 and not result.warnings
    # PostgreSQL
    assert db.get(KnowledgeSource, source.id) is None
    assert count(db, SourceVersion, SourceVersion.source_id == source.id) == 0
    assert count(db, KnowledgeDocument, KnowledgeDocument.id.in_([d.id for d in docs])) == 0
    assert count(db, DocumentChunk, DocumentChunk.knowledge_document_id.in_([d.id for d in docs])) == 0
    assert count(db, IngestionJob, IngestionJob.source_id == source.id) == 0
    # Qdrant
    assert all(store.count_document(d.id) == 0 for d in docs)
    # Files
    assert not any(f.exists() for f in files)
    # Audit
    event = db.scalar(select(AuditEvent).where(AuditEvent.action == "knowledge_source.deleted",
                                               AuditEvent.target_id == str(source.id)))
    assert event is not None and event.metadata_json["documents"] == 2

    # The other source is untouched.
    assert db.get(KnowledgeSource, keep_source.id) is not None
    assert store.count_document(keep_doc.id) > 0


def test_delete_api_requires_admin_and_returns_counts(db, settings, monkeypatch):
    from fastapi.testclient import TestClient

    from app.core.security import create_access_token
    from app.db.session import get_db
    from app.ingestion import config as ingestion_config
    from app.main import app

    for key, value in {"storage_dir": settings.storage_dir, "extracted_dir": settings.extracted_dir,
                       "qdrant_url": settings.qdrant_url, "qdrant_collection": settings.qdrant_collection}.items():
        monkeypatch.setenv(f"INGESTION_{key.upper()}", str(value))
    ingestion_config.get_ingestion_settings.cache_clear()

    admin, lawyer = make_user(db, "ADMIN"), make_user(db, "LAWYER")
    source, _, _ = ingest_statute(db, settings, admin)
    app.dependency_overrides[get_db] = lambda: db
    try:
        client = TestClient(app)
        as_lawyer = {"Authorization": f"Bearer {create_access_token(str(lawyer.id))}"}
        as_admin = {"Authorization": f"Bearer {create_access_token(str(admin.id))}"}
        assert client.delete(f"/api/v1/knowledge-sources/{source.id}", headers=as_lawyer).status_code == 403
        r = client.delete(f"/api/v1/knowledge-sources/{source.id}", headers=as_admin)
        assert r.status_code == 200, r.text
        assert r.json()["documents"] == 1
        assert client.delete(f"/api/v1/knowledge-sources/{source.id}", headers=as_admin).status_code == 404
    finally:
        app.dependency_overrides.clear()
        ingestion_config.get_ingestion_settings.cache_clear()
