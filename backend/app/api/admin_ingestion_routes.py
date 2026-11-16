"""
Admin ingestion monitoring (SCRUM-18). Admin only (KB administrator role).

Acceptance criteria:
  * "Ingestion status is recorded."           -> every stage writes an ingestion_jobs row
  * "Processing failures are visible."         -> /ingestion-jobs?status=failed, /summary, /documents/{id}/status
  * "Administrative operations are traceable." -> /audit-events, X-Request-ID

Endpoints (BRD §9 names):
    GET  /api/v1/admin/ingestion-jobs                job history, filterable
    POST /api/v1/admin/ingestion-jobs                start / retry processing of a document
    GET  /api/v1/admin/ingestion-jobs/summary        dashboard numbers + failed documents
    GET  /api/v1/admin/documents/{id}/status         one document's full processing timeline
    GET  /api/v1/admin/audit-events                  who did what, when
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.core.request_id import request_id_of
from app.db.session import get_db
from app.ingestion.config import get_ingestion_settings
from app.ingestion.pipeline import IN_PROGRESS_STATUSES, DocumentStatus
from app.ingestion.tasks import process_uploaded_document
from app.ingestion.vector_store import QdrantVectorStore
from app.models.audit_event import AuditEvent
from app.models.document_chunk import DocumentChunk
from app.models.ingestion_job import IngestionJob
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_source import KnowledgeSource
from app.models.source_version import SourceVersion
from app.models.user import User
from app.schemas.ingestion_monitoring import (
    AuditEventResponse,
    AuditListResponse,
    DocumentStatusResponse,
    FailedDocument,
    IngestionJobResponse,
    IngestionSummary,
    JobListResponse,
    ReprocessRequest,
    ReprocessResponse,
)
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/v1/admin", tags=["Admin: ingestion monitoring"])
admin_only = require_roles("ADMIN")

FAILED_DOCUMENT_STATUSES = (
    DocumentStatus.EMPTY, DocumentStatus.CORRUPTED, DocumentStatus.EXTRACTION_FAILED,
    DocumentStatus.CHUNKING_FAILED, DocumentStatus.INDEXING_FAILED, DocumentStatus.ACTIVATION_FAILED,
)


def _job_response(job: IngestionJob, filename: str | None) -> IngestionJobResponse:
    counts = job.counts or {}
    duration = None
    if job.started_at and job.finished_at:
        duration = round((job.finished_at - job.started_at).total_seconds() * 1000)
    return IngestionJobResponse(
        id=job.id,
        stage=counts.get("stage"),
        status=job.status,
        knowledge_document_id=job.knowledge_document_id,
        filename=filename,
        source_id=job.source_id,
        source_version_id=job.source_version_id,
        started_at=job.started_at,
        finished_at=job.finished_at,
        duration_ms=duration,
        error_code=(counts.get("error") or {}).get("code"),
        error_summary=job.error_summary,
        initiated_by=job.initiated_by,
        counts=counts,
    )


@router.get("/ingestion-jobs", response_model=JobListResponse)
def list_ingestion_jobs(
    status_filter: str | None = Query(None, alias="status", description="running / completed / failed"),
    stage: str | None = Query(None, description="text_extraction / chunking / indexing / activation"),
    document_id: UUID | None = None,
    source_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    conditions = []
    if status_filter:
        conditions.append(IngestionJob.status == status_filter)
    if stage:
        conditions.append(IngestionJob.counts["stage"].astext == stage)
    if document_id:
        conditions.append(IngestionJob.knowledge_document_id == document_id)
    if source_id:
        conditions.append(IngestionJob.source_id == source_id)

    total = db.scalar(select(func.count()).select_from(IngestionJob).where(*conditions)) or 0
    rows = db.execute(
        select(IngestionJob, KnowledgeDocument.filename)
        .outerjoin(KnowledgeDocument, KnowledgeDocument.id == IngestionJob.knowledge_document_id)
        .where(*conditions)
        .order_by(IngestionJob.started_at.desc().nulls_last(), IngestionJob.id)
        .limit(limit).offset(offset)
    ).all()
    return JobListResponse(total=total, items=[_job_response(job, name) for job, name in rows])


@router.post("/ingestion-jobs", response_model=ReprocessResponse, status_code=status.HTTP_202_ACCEPTED)
def start_ingestion(
    body: ReprocessRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    current_user: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    """Start (or retry after a failure) the full pipeline for one document."""
    document = db.get(KnowledgeDocument, body.document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    if document.processing_status in IN_PROGRESS_STATUSES:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Document is already being processed ({document.processing_status}).",
        )
    record_audit(
        db, actor_user_id=current_user.id, action="document.reprocess_requested",
        target_type="knowledge_document", target_id=document.id, request_id=request_id_of(request),
        metadata={"previous_status": document.processing_status},
    )
    db.commit()
    background_tasks.add_task(process_uploaded_document, document.id, current_user.id)
    return ReprocessResponse(document_id=document.id, message="Processing started.")


@router.get("/ingestion-jobs/summary", response_model=IngestionSummary)
def ingestion_summary(
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(hours=24)
    documents_by_status = dict(db.execute(
        select(KnowledgeDocument.processing_status, func.count()).group_by(KnowledgeDocument.processing_status)
    ).all())
    versions_by_status = dict(db.execute(
        select(SourceVersion.status, func.count()).group_by(SourceVersion.status)
    ).all())
    jobs_last_24h = dict(db.execute(
        select(IngestionJob.status, func.count()).where(IngestionJob.started_at >= since)
        .group_by(IngestionJob.status)
    ).all())
    code = IngestionJob.counts["error"]["code"].astext
    failures_by_code = {
        c or "UNKNOWN": n for c, n in db.execute(
            select(code, func.count())
            .where(IngestionJob.started_at >= since, IngestionJob.status == "failed")
            .group_by(code)
        ).all()
    }

    failed_docs = db.execute(
        select(KnowledgeDocument, KnowledgeSource.title)
        .join(SourceVersion, SourceVersion.id == KnowledgeDocument.source_version_id)
        .join(KnowledgeSource, KnowledgeSource.id == SourceVersion.source_id)
        .where(KnowledgeDocument.processing_status.in_(FAILED_DOCUMENT_STATUSES))
        .order_by(KnowledgeDocument.updated_at.desc())
        .limit(20)
    ).all()
    failed = []
    for document, title in failed_docs:
        last = db.scalar(
            select(IngestionJob).where(
                IngestionJob.knowledge_document_id == document.id, IngestionJob.status == "failed"
            ).order_by(IngestionJob.started_at.desc()).limit(1)
        )
        failed.append(FailedDocument(
            document_id=document.id, filename=document.filename, source_title=title,
            processing_status=document.processing_status,
            last_error=last.error_summary if last else None,
            failed_at=last.finished_at if last else None,
        ))

    return IngestionSummary(
        documents_by_status=documents_by_status,
        versions_by_status=versions_by_status,
        jobs_last_24h=jobs_last_24h,
        failures_last_24h_by_code=failures_by_code,
        in_progress=sum(documents_by_status.get(s, 0) for s in IN_PROGRESS_STATUSES),
        failed_documents=failed,
        vector_store=QdrantVectorStore(get_ingestion_settings()).health(),
    )


@router.get("/documents/{document_id}/status", response_model=DocumentStatusResponse)
def document_status(
    document_id: UUID,
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    document = db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    version = db.get(SourceVersion, document.source_version_id)
    source = db.get(KnowledgeSource, version.source_id)
    chunk_count = db.scalar(
        select(func.count()).select_from(DocumentChunk).where(DocumentChunk.knowledge_document_id == document.id)
    ) or 0
    try:
        vector_count = QdrantVectorStore(get_ingestion_settings()).count_document(document.id)
    except Exception:
        vector_count = None
    jobs = db.scalars(
        select(IngestionJob).where(IngestionJob.knowledge_document_id == document.id)
        .order_by(IngestionJob.started_at)
    )
    return DocumentStatusResponse(
        document_id=document.id,
        filename=document.filename,
        processing_status=document.processing_status,
        visibility=document.visibility,
        source_id=source.id,
        source_title=source.title,
        version_id=version.id,
        version_label=version.version_label,
        version_status=version.status,
        chunk_count=chunk_count,
        vector_count=vector_count,
        searchable=version.status == "active" and document.processing_status == DocumentStatus.COMPLETED,
        jobs=[_job_response(job, document.filename) for job in jobs],
    )


@router.get("/audit-events", response_model=AuditListResponse)
def list_audit_events(
    action: str | None = Query(None, description="e.g. source_version.activated"),
    target_id: str | None = None,
    actor_user_id: UUID | None = None,
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    conditions = []
    if action:
        conditions.append(AuditEvent.action == action)
    if target_id:
        conditions.append(AuditEvent.target_id == target_id)
    if actor_user_id:
        conditions.append(AuditEvent.actor_user_id == actor_user_id)
    total = db.scalar(select(func.count()).select_from(AuditEvent).where(*conditions)) or 0
    rows = db.execute(
        select(AuditEvent, User.email)
        .outerjoin(User, User.id == AuditEvent.actor_user_id)
        .where(*conditions)
        .order_by(AuditEvent.occurred_at.desc(), AuditEvent.id)
        .limit(limit).offset(offset)
    ).all()
    return AuditListResponse(total=total, items=[
        AuditEventResponse(
            id=e.id, actor_user_id=e.actor_user_id, actor_email=email, action=e.action,
            target_type=e.target_type, target_id=e.target_id, request_id=e.request_id,
            occurred_at=e.occurred_at, metadata=e.metadata_json,
        )
        for e, email in rows
    ])
