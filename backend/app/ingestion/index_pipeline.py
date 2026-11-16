"""
Indexing step of the ingestion pipeline (SCRUM-15).

Acceptance criteria:
  * "Embeddings are generated successfully."
  * "Vectors are stored in Qdrant."
  * "Chunk identifiers remain consistent across databases."
  * "Metadata is associated with the correct vectors."
  * "Indexing failures are identified."

WHAT `run_indexing()` DOES
--------------------------
    1. open an IngestionJob (stage "indexing"); document -> "indexing"; COMMIT
    2. load the document's chunks from PostgreSQL (document_chunks)
    3. embed every chunk's text in batches                  (embeddings.py)
    4. make sure the Qdrant collection exists with the right vector size
    5. replace this document's points in Qdrant: point id = chunk id
    6. VERIFY: read the points back and check
         * the number of points equals the number of chunks
         * every chunk id exists as a point id
         * each point's payload names the right chunk, document and text hash
    7. record the embedding model on each chunk row, document -> "indexed",
       job -> "completed" (or "failed" with a clear error code)

Possible failure codes (all visible in ingestion_jobs.error_summary):
    NO_CHUNKS_TO_INDEX, EMBEDDING_FAILED, VECTOR_STORE_UNAVAILABLE,
    VECTOR_DIMENSION_MISMATCH, INDEX_VERIFICATION_FAILED, UNEXPECTED_ERROR
"""

from __future__ import annotations

import hashlib
import logging
import time
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.config import IngestionSettings, get_ingestion_settings
from app.ingestion.embeddings import EmbeddingProvider, get_embedding_provider, validate_vectors
from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.pipeline import DocumentStatus, JobStatus, _now
from app.ingestion.vector_store import QdrantVectorStore, VectorPoint
from app.models.document_chunk import DocumentChunk
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_source import KnowledgeSource
from app.models.source_version import SourceVersion

logger = logging.getLogger(__name__)

STAGE = "indexing"
PREVIEW_CHARS = 300


def content_hash(text: str) -> str:
    """Fingerprint of a chunk's text, stored in Qdrant to detect mismatches."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_payload(
    chunk: DocumentChunk,
    document: KnowledgeDocument,
    version: SourceVersion | None,
    source: KnowledgeSource | None,
    model_name: str,
) -> dict[str, Any]:
    meta = chunk.chunk_metadata or {}
    return {
        # --- identifiers (all as strings: Qdrant payloads are JSON) ---
        "chunk_id": str(chunk.id),
        "knowledge_document_id": str(document.id),
        "source_version_id": str(chunk.source_version_id),
        "source_id": str(source.id) if source else None,
        "chunk_index": chunk.chunk_index,
        # --- where in the document ---
        "section_ref": chunk.section_ref,
        "page_number": chunk.page_number,
        "page_end": meta.get("page_end"),
        # --- filterable source metadata (BRD §8.4) ---
        "source_title": source.title if source else None,
        "source_type": source.source_type if source else None,
        "jurisdiction": source.jurisdiction if source else None,
        "trust_tier": source.trust_tier if source else None,
        "publisher": source.publisher if source else None,
        "published_date": version.published_at.isoformat() if version and version.published_at else None,
        # --- access control ---
        "visibility": document.visibility,
        "matter_id": None,  # private case files are a later story
        "uploaded_by": str(document.uploaded_by),
        # --- integrity ---
        "content_hash": content_hash(chunk.text),
        "embedding_model": model_name,
        "text_preview": chunk.text[:PREVIEW_CHARS],
    }


def verify_index(store: QdrantVectorStore, document_id: UUID, chunks: list[DocumentChunk]) -> dict[str, Any]:
    """Step 6: prove ids and metadata line up between PostgreSQL and Qdrant."""
    stored = store.count_document(document_id)
    if stored != len(chunks):
        raise ExtractionError(
            ExtractionErrorCode.INDEX_VERIFICATION_FAILED,
            f"Qdrant holds {stored} vectors for this document but PostgreSQL has {len(chunks)} chunks.",
            details={"qdrant_points": stored, "postgres_chunks": len(chunks)},
        )
    points = store.retrieve([c.id for c in chunks])
    problems = []
    for chunk in chunks:
        point = points.get(chunk.id)
        if point is None:
            problems.append({"chunk_id": str(chunk.id), "problem": "missing point"})
        elif point.payload.get("chunk_id") != str(chunk.id):
            problems.append({"chunk_id": str(chunk.id), "problem": "payload chunk_id differs"})
        elif point.payload.get("knowledge_document_id") != str(document_id):
            problems.append({"chunk_id": str(chunk.id), "problem": "payload document differs"})
        elif point.payload.get("content_hash") != content_hash(chunk.text):
            problems.append({"chunk_id": str(chunk.id), "problem": "text hash differs"})
    if problems:
        raise ExtractionError(
            ExtractionErrorCode.INDEX_VERIFICATION_FAILED,
            f"{len(problems)} vector(s) do not match their chunk in PostgreSQL.",
            details={"problems": problems[:10]},
        )
    return {"verified_points": stored}


def run_indexing(
    db: Session,
    document_id: UUID,
    initiated_by: UUID,
    *,
    settings: IngestionSettings | None = None,
    provider: EmbeddingProvider | None = None,
    store: QdrantVectorStore | None = None,
) -> IngestionJob:
    """Embed and index one chunked document; always returns the job row."""
    settings = settings or get_ingestion_settings()
    store = store or QdrantVectorStore(settings)

    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise ValueError(f"KnowledgeDocument {document_id} does not exist.")
    version = db.get(SourceVersion, document.source_version_id)
    source = db.get(KnowledgeSource, version.source_id) if version else None

    base_counts: dict[str, Any] = {"stage": STAGE, "document_id": str(document.id)}
    job = IngestionJob(
        source_id=source.id if source else None,
        source_version_id=document.source_version_id,
        knowledge_document_id=document.id,
        status=JobStatus.RUNNING,
        started_at=_now(),
        initiated_by=initiated_by,
        counts=base_counts,
    )
    db.add(job)
    document.processing_status = DocumentStatus.INDEXING
    db.commit()

    started = time.perf_counter()
    try:
        chunks = list(
            db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.knowledge_document_id == document.id)
                .order_by(DocumentChunk.chunk_index)
            )
        )
        if not chunks:
            raise ExtractionError(
                ExtractionErrorCode.NO_CHUNKS_TO_INDEX,
                "This document has no chunks; run chunking first.",
            )

        provider = provider or get_embedding_provider(settings)
        dimension = provider.dimension
        store.ensure_collection(dimension)

        vectors = provider.embed_documents([c.text for c in chunks])
        validate_vectors(vectors, len(chunks), dimension, provider.name)

        points = [
            VectorPoint(chunk.id, vector, build_payload(chunk, document, version, source, provider.name))
            for chunk, vector in zip(chunks, vectors)
        ]
        store.replace_document_points(document.id, points)
        verification = verify_index(store, document.id, chunks)

        indexed_at = _now().isoformat()
        for chunk in chunks:
            # New dict so SQLAlchemy notices the JSONB change.
            chunk.chunk_metadata = {
                **(chunk.chunk_metadata or {}),
                "vector_id": str(chunk.id),
                "embedding_model": provider.name,
                "qdrant_collection": store.collection,
                "indexed_at": indexed_at,
            }

        document.processing_status = DocumentStatus.INDEXED
        job.status = JobStatus.COMPLETED
        job.counts = {
            **base_counts,
            "vectors": len(points),
            "dimension": dimension,
            "embedding_model": provider.name,
            "collection": store.collection,
            **verification,
            "duration_ms": round((time.perf_counter() - started) * 1000),
        }
        logger.info("Indexed document %s: %s vectors", document.id, len(points))

    except ExtractionError as exc:
        logger.warning("Indexing failed for document %s: %s", document.id, exc)
        db.rollback()
        document.processing_status = DocumentStatus.INDEXING_FAILED
        job.status = JobStatus.FAILED
        job.error_summary = str(exc)
        job.counts = {**base_counts, "error": exc.to_dict()}

    except Exception as exc:
        logger.exception("Unexpected error indexing document %s", document.id)
        db.rollback()
        error = ExtractionError(
            ExtractionErrorCode.UNEXPECTED_ERROR,
            f"Unexpected {type(exc).__name__} during indexing.",
        )
        document.processing_status = DocumentStatus.INDEXING_FAILED
        job.status = JobStatus.FAILED
        job.error_summary = str(error)
        job.counts = {**base_counts, "error": error.to_dict()}

    job.finished_at = _now()
    db.commit()
    return job
