"""
Activation: the last ingestion stage, and edition (version) management
(SCRUM-18).

Acceptance criteria:
  * "Source versions are maintained."
  * "Previous versions are preserved."
  * "Administrative operations are traceable."

BRD §10.1: "Source Activation: make a document available for retrieval only
after the required validation checks have passed" and "Version Management:
preserve previous source versions ... retire or supersede outdated versions
through an auditable administrative process."

HOW EDITIONS WORK
-----------------
A knowledge source (e.g. "Indian Contract Act, 1872") has one or more
editions in `source_versions`. At most ONE edition is `active` (searchable).

    upload edition 2023  ->  pending  --pipeline-->  active
    upload edition 2024  ->  pending  --pipeline-->  active
                             and edition 2023 becomes superseded
                             (2024.supersedes_version_id = 2023)

Nothing is deleted when an edition is superseded or withdrawn: its file,
extracted text, chunks and vectors all stay, so old answers can still be
traced to the exact text they used, and an admin can roll back by
activating the older edition again. Search simply ignores editions that
are not `active` (app/rag/store_retriever.py).

Statuses (CHECK rule on source_versions.status):
    pending     uploaded, not processed yet
    active      the searchable edition
    superseded  replaced by a newer edition (kept for history)
    withdrawn   removed from search by an admin (kept for history)
    failed      processing failed
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.config import IngestionSettings, get_ingestion_settings
from app.ingestion.errors import ExtractionError, ExtractionErrorCode
from app.ingestion.pipeline import DocumentStatus, JobStatus, _now
from app.ingestion.vector_store import QdrantVectorStore
from app.models.document_chunk import DocumentChunk
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.models.source_version import SourceVersion
from app.services.audit_service import record_audit

logger = logging.getLogger(__name__)

STAGE = "activation"


class VersionStatus:
    PENDING = "pending"
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    WITHDRAWN = "withdrawn"
    FAILED = "failed"


# Document statuses that mean "fully processed" (searchable once its
# edition is active).
READY_DOCUMENT_STATUSES = frozenset({DocumentStatus.COMPLETED})


def activate_version(
    db: Session,
    version: SourceVersion,
    *,
    actor_user_id: UUID | None,
    reason: str,
    request_id: str | None = None,
) -> list[SourceVersion]:
    """
    Make `version` the active edition of its source and supersede the
    previously active one(s). Returns the editions that were superseded.
    Adds audit rows; the caller commits.
    """
    documents = list(db.scalars(select(KnowledgeDocument).where(KnowledgeDocument.source_version_id == version.id)))
    not_ready = [d for d in documents if d.processing_status not in READY_DOCUMENT_STATUSES]
    if not documents or not_ready:
        raise ValueError(
            "This edition cannot be activated until all its documents have finished processing "
            f"({len(not_ready)} of {len(documents)} not ready)."
        )

    previous = list(db.scalars(
        select(SourceVersion)
        .where(
            SourceVersion.source_id == version.source_id,
            SourceVersion.id != version.id,
            SourceVersion.status == VersionStatus.ACTIVE,
        )
        .order_by(SourceVersion.retrieved_at.desc())
    ))
    for old in previous:
        old.status = VersionStatus.SUPERSEDED
        record_audit(
            db, actor_user_id=actor_user_id, action="source_version.superseded",
            target_type="source_version", target_id=old.id, request_id=request_id,
            metadata={"source_id": str(old.source_id), "superseded_by": str(version.id)},
        )
    # Link the new edition to the one it replaces (the history chain).
    if previous and version.supersedes_version_id is None:
        version.supersedes_version_id = previous[0].id

    version.status = VersionStatus.ACTIVE
    record_audit(
        db, actor_user_id=actor_user_id, action="source_version.activated",
        target_type="source_version", target_id=version.id, request_id=request_id,
        metadata={
            "source_id": str(version.source_id),
            "reason": reason,
            "superseded": [str(v.id) for v in previous],
            "documents": [str(d.id) for d in documents],
        },
    )
    return previous


def withdraw_version(
    db: Session,
    version: SourceVersion,
    *,
    actor_user_id: UUID | None,
    reason: str,
    request_id: str | None = None,
) -> None:
    """Remove an edition from search without deleting anything. Caller commits."""
    if version.status == VersionStatus.WITHDRAWN:
        raise ValueError("This edition is already withdrawn.")
    previous_status = version.status
    version.status = VersionStatus.WITHDRAWN
    record_audit(
        db, actor_user_id=actor_user_id, action="source_version.withdrawn",
        target_type="source_version", target_id=version.id, request_id=request_id,
        metadata={"source_id": str(version.source_id), "reason": reason, "previous_status": previous_status},
    )


def run_activation(
    db: Session,
    document_id: UUID,
    initiated_by: UUID,
    *,
    settings: IngestionSettings | None = None,
    store: QdrantVectorStore | None = None,
) -> IngestionJob:
    """
    Final pipeline stage: re-check the document, mark it `completed`, and
    activate its edition once every document of the edition is ready.
    """
    settings = settings or get_ingestion_settings()
    store = store or QdrantVectorStore(settings)

    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise ValueError(f"KnowledgeDocument {document_id} does not exist.")
    version = db.get(SourceVersion, document.source_version_id)

    base_counts: dict[str, Any] = {"stage": STAGE, "document_id": str(document.id)}
    job = IngestionJob(
        source_id=version.source_id if version else None,
        source_version_id=document.source_version_id,
        knowledge_document_id=document.id,
        status=JobStatus.RUNNING,
        started_at=_now(),
        initiated_by=initiated_by,
        counts=base_counts,
    )
    db.add(job)
    db.commit()

    try:
        # ---- final quality checks (BRD §10.1 "Quality Validation") ----
        if document.processing_status != DocumentStatus.INDEXED:
            raise ExtractionError(
                ExtractionErrorCode.ACTIVATION_CHECK_FAILED,
                f"Document must be 'indexed' before activation (it is '{document.processing_status}').",
            )
        chunks = db.scalar(
            select(func.count()).select_from(DocumentChunk).where(DocumentChunk.knowledge_document_id == document.id)
        ) or 0
        vectors = store.count_document(document.id)
        if chunks == 0 or vectors != chunks:
            raise ExtractionError(
                ExtractionErrorCode.ACTIVATION_CHECK_FAILED,
                f"Chunk/vector counts do not match ({chunks} chunks, {vectors} vectors).",
                details={"chunks": chunks, "vectors": vectors},
            )

        document.processing_status = DocumentStatus.COMPLETED
        db.flush()

        # ---- edition: activate only new/failed/current editions --------
        # Re-processing a document of a superseded or withdrawn edition must
        # never silently bring that old edition back into search.
        activated, superseded = False, []
        if version is not None and version.status in (VersionStatus.PENDING, VersionStatus.FAILED, VersionStatus.ACTIVE):
            try:
                superseded = activate_version(
                    db, version, actor_user_id=initiated_by, reason="automatic after successful ingestion"
                )
                activated = True
            except ValueError as exc:
                # Other files of this edition are still processing; the last
                # one to finish will activate the edition.
                logger.info("Edition %s not activated yet: %s", version.id, exc)

        job.status = JobStatus.COMPLETED
        job.counts = {
            **base_counts,
            "chunks": chunks,
            "vectors": vectors,
            "version_status": version.status if version else None,
            "version_activated": activated,
            "superseded_versions": [str(v.id) for v in superseded],
        }

    except ExtractionError as exc:
        logger.warning("Activation failed for document %s: %s", document.id, exc)
        db.rollback()
        document.processing_status = DocumentStatus.ACTIVATION_FAILED
        job.status = JobStatus.FAILED
        job.error_summary = str(exc)
        job.counts = {**base_counts, "error": exc.to_dict()}

    except Exception as exc:
        logger.exception("Unexpected error activating document %s", document.id)
        db.rollback()
        error = ExtractionError(ExtractionErrorCode.UNEXPECTED_ERROR,
                                f"Unexpected {type(exc).__name__} during activation.")
        document.processing_status = DocumentStatus.ACTIVATION_FAILED
        job.status = JobStatus.FAILED
        job.error_summary = str(error)
        job.counts = {**base_counts, "error": error.to_dict()}

    job.finished_at = _now()
    db.commit()
    return job
