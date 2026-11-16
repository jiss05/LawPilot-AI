"""
SCRUM-15 acceptance criteria:
  * Embeddings are generated successfully.
  * Vectors are stored in Qdrant.
  * Chunk identifiers remain consistent across databases.
  * Metadata is associated with the correct vectors.
  * Indexing failures are identified.

Qdrant runs EMBEDDED here (QDRANT_URL=":memory:"): the real Qdrant engine
inside the test process, with the same API as the Docker container. The
"hashing" embedding provider needs no model download.
"""

import math
import uuid

import pytest

from app.ingestion.chunk_pipeline import run_chunking
from app.ingestion.embeddings import (
    HashingEmbeddingProvider,
    get_embedding_provider,
    validate_vectors,
)
from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.extractor import DocumentExtractor
from app.ingestion.index_pipeline import content_hash, run_indexing
from app.ingestion.pipeline import DocumentStatus, JobStatus, run_extraction
from app.ingestion.vector_store import QdrantVectorStore

from .test_chunk_pipeline import FakeSession, world  # noqa: F401  (fixture reuse)


def prepared(world):
    """Run extraction + chunking so the document is ready to index."""
    db, document, source, version, settings = world
    run_extraction(db, document.id, document.uploaded_by, extractor=DocumentExtractor(settings), settings=settings)
    run_chunking(db, document.id, document.uploaded_by, settings=settings)
    return db, document, source, version, settings


# --------------------------------------------------------------------------
# Embeddings
# --------------------------------------------------------------------------
def test_hashing_embeddings_are_normalised_and_similar_for_similar_text():
    provider = HashingEmbeddingProvider(64)
    a, b, c = provider.embed_documents([
        "compensation for breach of contract",
        "breach of contract compensation claim",
        "registration of a motor vehicle",
    ])
    assert len(a) == 64 and math.isclose(sum(v * v for v in a), 1.0, rel_tol=1e-6)
    dot = lambda x, y: sum(i * j for i, j in zip(x, y))
    assert dot(a, b) > dot(a, c)


def test_bad_vectors_are_rejected():
    with pytest.raises(ExtractionError) as info:
        validate_vectors([[0.1, float("nan")]], 1, 2, "test")
    assert info.value.code == ExtractionErrorCode.EMBEDDING_FAILED
    with pytest.raises(ExtractionError):
        validate_vectors([[0.1, 0.2, 0.3]], 1, 2, "test")  # wrong size
    with pytest.raises(ExtractionError):
        validate_vectors([], 1, 2, "test")  # missing vector


def test_unknown_provider_name_is_a_clear_error(settings):
    with pytest.raises(ValueError, match="Unknown INGESTION_EMBEDDING_PROVIDER"):
        get_embedding_provider(settings.model_copy(update={"embedding_provider": "magic"}))


# --------------------------------------------------------------------------
# Indexing
# --------------------------------------------------------------------------
def test_vectors_stored_with_same_ids_and_correct_metadata(world):
    db, document, source, version, settings = prepared(world)
    job = run_indexing(db, document.id, document.uploaded_by, settings=settings)

    assert job.status == JobStatus.COMPLETED, job.error_summary
    assert document.processing_status == DocumentStatus.INDEXED
    chunks = db.chunks()
    assert job.counts["vectors"] == job.counts["verified_points"] == len(chunks)
    assert job.counts["dimension"] == 64

    store = QdrantVectorStore(settings)
    points = store.retrieve([c.id for c in chunks])
    assert set(points) == {c.id for c in chunks}            # same ids in both databases
    for chunk in chunks:
        payload = points[chunk.id].payload
        assert payload["chunk_id"] == str(chunk.id)
        assert payload["knowledge_document_id"] == str(document.id)
        assert payload["source_version_id"] == str(version.id)
        assert payload["source_id"] == str(source.id)
        assert payload["section_ref"] == chunk.section_ref
        assert payload["page_number"] == chunk.page_number
        assert payload["source_title"] == "Sample Contract Act, 1872"
        assert payload["visibility"] == document.visibility
        assert payload["content_hash"] == content_hash(chunk.text)
        assert chunk.chunk_metadata["vector_id"] == str(chunk.id)
        assert chunk.chunk_metadata["embedding_model"] == "hashing:64"


def test_reindexing_replaces_vectors_instead_of_duplicating(world):
    db, document, *_ , settings = prepared(world)
    run_indexing(db, document.id, document.uploaded_by, settings=settings)
    run_indexing(db, document.id, document.uploaded_by, settings=settings)
    assert QdrantVectorStore(settings).count_document(document.id) == len(db.chunks())


def test_semantic_search_finds_the_right_section(world):
    db, document, *_ , settings = prepared(world)
    run_indexing(db, document.id, document.uploaded_by, settings=settings)
    provider = get_embedding_provider(settings)
    hits = QdrantVectorStore(settings).search(
        provider.embed_query("penalty stipulated in the contract"), limit=3
    )
    assert hits[0].payload["section_ref"] == "Section 74"


# --------------------------------------------------------------------------
# Failures are identified
# --------------------------------------------------------------------------
def test_indexing_without_chunks_fails_clearly(world):
    db, document, *_ , settings = world
    job = run_indexing(db, document.id, document.uploaded_by, settings=settings)
    assert job.status == JobStatus.FAILED
    assert job.error_summary.startswith("[NO_CHUNKS_TO_INDEX]")
    assert document.processing_status == DocumentStatus.INDEXING_FAILED


def test_qdrant_down_is_reported(world):
    db, document, *_ , settings = prepared(world)
    down = settings.model_copy(update={"qdrant_url": "http://127.0.0.1:1", "qdrant_timeout_seconds": 1})
    job = run_indexing(db, document.id, document.uploaded_by, settings=down)
    assert job.status == JobStatus.FAILED
    assert job.counts["error"]["code"] == "VECTOR_STORE_UNAVAILABLE"
    assert "Is the qdrant container running?" in job.error_summary


def test_changed_embedding_model_is_caught(world):
    db, document, *_ , settings = prepared(world)
    run_indexing(db, document.id, document.uploaded_by, settings=settings)
    bigger = HashingEmbeddingProvider(128)  # a "different model" with another size
    job = run_indexing(db, document.id, document.uploaded_by, settings=settings, provider=bigger)
    assert job.counts["error"]["code"] == "VECTOR_DIMENSION_MISMATCH"


def test_embedding_failure_is_reported(world):
    db, document, *_ , settings = prepared(world)

    class BrokenModel(HashingEmbeddingProvider):
        def embed_documents(self, texts):
            return [[float("nan")] * self.dimension for _ in texts]

    job = run_indexing(db, document.id, document.uploaded_by, settings=settings, provider=BrokenModel(64))
    assert job.counts["error"]["code"] == "EMBEDDING_FAILED"


def test_verification_catches_missing_vectors(world, monkeypatch):
    db, document, *_ , settings = prepared(world)
    original = QdrantVectorStore.replace_document_points

    def drop_one(self, document_id, points):
        return original(self, document_id, points[:-1])  # "lose" a vector

    monkeypatch.setattr(QdrantVectorStore, "replace_document_points", drop_one)
    job = run_indexing(db, document.id, document.uploaded_by, settings=settings)
    assert job.counts["error"]["code"] == "INDEX_VERIFICATION_FAILED"
    assert job.counts["error"]["details"]["qdrant_points"] == len(db.chunks()) - 1


def test_unknown_document_raises(settings):
    with pytest.raises(ValueError):
        run_indexing(FakeSession(), uuid.uuid4(), uuid.uuid4(), settings=settings)
