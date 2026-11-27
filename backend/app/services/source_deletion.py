"""
Delete a legal source and everything derived from it.

    knowledge_sources ─┬─ source_versions ─┬─ knowledge_documents ─┬─ document_chunks   (PostgreSQL)
                       │                   │                       ├─ vectors           (Qdrant)
                       │                   │                       ├─ original PDF      (INGESTION_STORAGE_DIR)
                       │                   │                       └─ extracted text    (INGESTION_EXTRACTED_DIR)
                       └─ ingestion_jobs ──┘
Order matters:
  1. Qdrant first. If the vector store is unreachable nothing is deleted, so
     the database never refers to vectors that are gone, or the reverse.
  2. PostgreSQL in ONE transaction: chunks, ingestion jobs, documents,
     editions, the source. Rows in `citations` (saved chat answers) keep their
     text but lose the link to the deleted chunk/edition.
  3. Files on disk, after the commit (best effort; a leftover file is
     reported, never a reason to roll back).
  4. One audit event: knowledge_source.deleted, with counts only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from uuid import UUID

from sqlalchemy import delete, func, or_, select, update
from sqlalchemy.orm import Session

from app.ingestion.config import IngestionSettings, get_ingestion_settings
from app.ingestion.pipeline import DocumentStatus
from app.ingestion.storage import extraction_output_path, resolve_storage_path
from app.ingestion.vector_store import QdrantVectorStore
from app.models.citation import Citation
from app.models.document_chunk import DocumentChunk
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_source import KnowledgeSource
from app.models.source_version import SourceVersion
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

BUSY_STATUSES = frozenset({DocumentStatus.EXTRACTING, DocumentStatus.CHUNKING, DocumentStatus.INDEXING})


class SourceNotFound(Exception):
    pass


class SourceBusy(Exception):
    """A document of the source is still being processed."""


class VectorStoreUnavailable(Exception):
    """Qdrant could not be reached; nothing was deleted."""


@dataclass
class DeletionResult:
    source_id: UUID
    title: str
    versions: int
    documents: int
    chunks: int
    files_deleted: int
    warnings: list[str] = field(default_factory=list)


def delete_legal_source(
    db: Session,
    source_id: UUID,
    *,
    actor_user_id: UUID,
    request_id: str | None = None,
    force: bool = False,
    vector_store: QdrantVectorStore | None = None,
    settings: IngestionSettings | None = None,
) -> DeletionResult:
    settings = settings or get_ingestion_settings()

    source = db.get(KnowledgeSource, source_id)
    if source is None:
        raise SourceNotFound(str(source_id))
    title = source.title

    version_ids = list(db.scalars(select(SourceVersion.id).where(SourceVersion.source_id == source_id)).all())
    documents = list(
        db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.source_version_id.in_(version_ids))).all()
    ) if version_ids else []
    document_ids = [d.id for d in documents]

    busy = [d for d in documents if d.processing_status in BUSY_STATUSES]
    if busy and not force:
        raise SourceBusy(", ".join(d.filename for d in busy))

    # ---- 1. Qdrant ---------------------------------------------------------- #
    store = vector_store or QdrantVectorStore(settings)
    try:
        for document_id in document_ids:
            store.delete_document(document_id)
    except Exception as exc:
        logger.warning("Vector deletion failed for source %s: %s", source_id, type(exc).__name__)
        raise VectorStoreUnavailable() from exc

    # ---- 2. PostgreSQL (one transaction) ------------------------------------- #
    chunk_filter = or_(
        DocumentChunk.knowledge_document_id.in_(document_ids) if document_ids else False,
        DocumentChunk.source_version_id.in_(version_ids) if version_ids else False,
    )
    chunk_count = db.scalar(select(func.count()).select_from(DocumentChunk).where(chunk_filter)) or 0
    try:
        if version_ids or document_ids:
            chunk_ids = select(DocumentChunk.id).where(chunk_filter).scalar_subquery()
            db.execute(update(Citation).where(Citation.chunk_id.in_(chunk_ids)).values(chunk_id=None))
            if version_ids:
                db.execute(update(Citation).where(Citation.source_version_id.in_(version_ids))
                           .values(source_version_id=None))
            db.execute(delete(DocumentChunk).where(chunk_filter))

        job_conditions = [IngestionJob.source_id == source_id]
        if version_ids:
            job_conditions.append(IngestionJob.source_version_id.in_(version_ids))
        if document_ids:
            job_conditions.append(IngestionJob.knowledge_document_id.in_(document_ids))
        db.execute(delete(IngestionJob).where(or_(*job_conditions)))

        if document_ids:
            db.execute(delete(KnowledgeDocument).where(KnowledgeDocument.id.in_(document_ids)))
        if version_ids:
            db.execute(update(SourceVersion).where(SourceVersion.source_id == source_id)
                       .values(supersedes_version_id=None))
            db.execute(delete(SourceVersion).where(SourceVersion.source_id == source_id))
        db.execute(delete(KnowledgeSource).where(KnowledgeSource.id == source_id))

        record_audit(
            db,
            actor_user_id=actor_user_id,
            action="knowledge_source.deleted",
            target_type="knowledge_source",
            target_id=source_id,
            metadata={
                "title": title[:200],
                "versions": len(version_ids),
                "documents": len(document_ids),
                "chunks": chunk_count,
                "forced": bool(busy),
            },
            request_id=request_id,
        )
        db.commit()
    except Exception:
        db.rollback()
        raise

    # ---- 3. Files ----------------------------------------------------------- #
    files_deleted = 0
    warnings: list[str] = []
    for doc in documents:
        paths = []
        try:
            paths.append(resolve_storage_path(doc.storage_key, settings))
        except Exception:
            warnings.append(f"Unsafe storage path skipped for {doc.filename}.")
        paths.append(extraction_output_path(doc.id, settings))
        for path in paths:
            try:
                if path.exists():
                    path.unlink()
                    files_deleted += 1
            except OSError as exc:
                logger.warning("Could not delete %s: %s", path.name, exc)
                warnings.append(f"Could not delete file {path.name}; remove it manually.")

    return DeletionResult(
        source_id=source_id,
        title=title,
        versions=len(version_ids),
        documents=len(document_ids),
        chunks=chunk_count,
        files_deleted=files_deleted,
        warnings=warnings,
    )
