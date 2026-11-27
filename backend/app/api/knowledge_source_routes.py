
from datetime import date
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
    status,
)
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.core.request_id import request_id_of
from app.ingestion.activation import activate_version, withdraw_version
from app.ingestion.tasks import process_uploaded_document
from app.models.document_chunk import DocumentChunk
from app.models.knowledge_document import KnowledgeDocument
from app.models.source_version import SourceVersion
from app.schemas.knowledge_source import (
    KnowledgeSourceResponse,
    KnowledgeDocumentResponse,
    SourceVersionResponse,
    VersionActionRequest,
    VersionActionResponse,
    VersionDocumentSummary,
)
from app.services.knowledge_source_service import (
    register_legal_source,
    register_source_version,
    get_legal_sources,
    get_legal_source,
    get_source_documents,
)

VISIBILITIES = ("public", "internal", "private")
MAX_UPLOAD_BYTES = 20 * 1024 * 1024


router = APIRouter(
    prefix="/api/v1/knowledge-sources",
    tags=["Legal Source Registry"],
)


@router.post(
    "",
    response_model=KnowledgeSourceResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_legal_source(
    # FastAPI fills these in automatically (no default needed); they must
    # come first because Python does not allow a parameter without a
    # default after parameters that have one.
    background_tasks: BackgroundTasks,
    request: Request,
    title: str = Form(...),
    source_type: str = Form(...),
    jurisdiction: str = Form(...),
    trust_tier: str = Form(...),
    publisher: str | None = Form(None),
    canonical_url: str | None = Form(None),
    version_label: str | None = Form(None),
    published_at: date | None = Form(None),
    # Who may retrieve this document (see app/rag/filters.py):
    #   public   - every logged-in user (approved legal sources, BRD FR-020)
    #   internal - lawyers, judge-support users and admins only
    #   private  - the uploader and admins only
    visibility: str = Form("public"),
    file: UploadFile = File(...),
    current_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    if visibility not in ("public", "internal", "private"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="visibility must be public, internal or private.",
        )

    if file.filename is None or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF files are accepted.",
        )

    if file.content_type not in ("application/pdf", "application/octet-stream"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid PDF content type.",
        )

    file_content = await file.read(20 * 1024 * 1024 + 1)

    try:
        source, document = register_legal_source(
            db,
            title=title,
            source_type=source_type,
            jurisdiction=jurisdiction,
            trust_tier=trust_tier,
            publisher=publisher,
            canonical_url=canonical_url,
            version_label=version_label,
            published_at=published_at,
            original_filename=file.filename,
            file_content=file_content,
            uploaded_by=current_user.id,
            visibility=visibility,
            request_id=request_id_of(request),
        )

        # Start text extraction + cleaning + chunking AFTER the response
        # is sent. The admin gets "201 Created" immediately instead of
        # waiting for OCR, and can follow progress through
        # knowledge_documents.processing_status and ingestion_jobs.
        # (FastAPI runs background tasks in the same server process; a
        # dedicated job queue such as Celery can replace this later,
        # BRD NFR-03.)
        background_tasks.add_task(
            process_uploaded_document, document.id, current_user.id
        )

        return source

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )


@router.get(
    "",
    response_model=list[KnowledgeSourceResponse],
)
def list_legal_sources(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return get_legal_sources(db)


@router.get(
    "/{source_id}",
    response_model=KnowledgeSourceResponse,
)
def retrieve_legal_source(
    source_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = get_legal_source(db, source_id)

    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Legal source not found.",
        )

    return source


@router.get(
    "/{source_id}/documents",
    response_model=list[KnowledgeDocumentResponse],
)
def retrieve_source_documents(
    source_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    source = get_legal_source(db, source_id)

    if source is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Legal source not found.",
        )

    return get_source_documents(db, source_id)




# ---------------------------------------------------------------------------
# Editions / source versions (SCRUM-18). Admin only.
# ---------------------------------------------------------------------------
def _version_response(db: Session, version: SourceVersion) -> SourceVersionResponse:
    documents = list(db.scalars(
        select(KnowledgeDocument).where(KnowledgeDocument.source_version_id == version.id)
        .order_by(KnowledgeDocument.uploaded_at)
    ))
    counts = dict(db.execute(
        select(DocumentChunk.knowledge_document_id, func.count())
        .where(DocumentChunk.knowledge_document_id.in_([d.id for d in documents]))
        .group_by(DocumentChunk.knowledge_document_id)
    ).all()) if documents else {}
    return SourceVersionResponse(
        id=version.id,
        source_id=version.source_id,
        version_label=version.version_label,
        published_at=version.published_at,
        retrieved_at=version.retrieved_at,
        status=version.status,
        content_hash=version.content_hash,
        supersedes_version_id=version.supersedes_version_id,
        documents=[
            VersionDocumentSummary(
                id=d.id, filename=d.filename, processing_status=d.processing_status,
                visibility=d.visibility, uploaded_at=d.uploaded_at, chunk_count=counts.get(d.id, 0),
            )
            for d in documents
        ],
    )


def _get_source_or_404(db: Session, source_id: UUID):
    source = get_legal_source(db, source_id)
    if source is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal source not found.")
    return source


def _get_version_or_404(db: Session, source_id: UUID, version_id: UUID) -> SourceVersion:
    version = db.get(SourceVersion, version_id)
    if version is None or version.source_id != source_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Source version not found.")
    return version


@router.post(
    "/{source_id}/versions",
    response_model=SourceVersionResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_source_version(
    source_id: UUID,
    background_tasks: BackgroundTasks,
    request: Request,
    version_label: str | None = Form(None),
    published_at: date | None = Form(None),
    visibility: str = Form("public"),
    file: UploadFile = File(...),
    current_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Upload a new edition (e.g. an amended Act). It is processed in the
    background; when it passes all checks it becomes the active edition and
    the previous one is marked superseded (but kept).
    """
    source = _get_source_or_404(db, source_id)
    if visibility not in VISIBILITIES:
        raise HTTPException(status_code=400, detail="visibility must be public, internal or private.")
    if file.filename is None or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are accepted.")

    file_content = await file.read(MAX_UPLOAD_BYTES + 1)
    try:
        version, document = register_source_version(
            db, source=source, version_label=version_label, published_at=published_at,
            original_filename=file.filename, file_content=file_content,
            uploaded_by=current_user.id, visibility=visibility, request_id=request_id_of(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    background_tasks.add_task(process_uploaded_document, document.id, current_user.id)
    return _version_response(db, version)


@router.get("/{source_id}/versions", response_model=list[SourceVersionResponse])
def list_source_versions(
    source_id: UUID,
    current_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    """Full edition history of a source, newest first. Nothing is ever deleted."""
    _get_source_or_404(db, source_id)
    versions = db.scalars(
        select(SourceVersion).where(SourceVersion.source_id == source_id)
        .order_by(SourceVersion.retrieved_at.desc())
    )
    return [_version_response(db, v) for v in versions]


@router.post("/{source_id}/versions/{version_id}/activate", response_model=VersionActionResponse)
def activate_source_version(
    source_id: UUID,
    version_id: UUID,
    body: VersionActionRequest,
    request: Request,
    current_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Make this edition the searchable one, e.g. to ROLL BACK to an older
    edition. The currently active edition becomes superseded.
    """
    version = _get_version_or_404(db, source_id, version_id)
    if version.status == "active":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="This edition is already active.")
    try:
        superseded = activate_version(
            db, version, actor_user_id=current_user.id, reason=body.reason,
            request_id=request_id_of(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    db.commit()
    db.refresh(version)
    return VersionActionResponse(
        version=_version_response(db, version), superseded_version_ids=[v.id for v in superseded]
    )


@router.post("/{source_id}/versions/{version_id}/withdraw", response_model=VersionActionResponse)
def withdraw_source_version(
    source_id: UUID,
    version_id: UUID,
    body: VersionActionRequest,
    request: Request,
    current_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    """Remove an edition from search (e.g. published in error). Nothing is deleted."""
    version = _get_version_or_404(db, source_id, version_id)
    try:
        withdraw_version(
            db, version, actor_user_id=current_user.id, reason=body.reason,
            request_id=request_id_of(request),
        )
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    db.commit()
    db.refresh(version)
    return VersionActionResponse(version=_version_response(db, version))


# ---------------------------------------------------------------------------
# Delete a source and everything derived from it
# ---------------------------------------------------------------------------
class SourceDeleteResponse(BaseModel):
    source_id: UUID
    title: str
    versions: int
    documents: int
    chunks: int
    files_deleted: int
    warnings: list[str] = []


@router.delete("/{source_id}", response_model=SourceDeleteResponse)
def delete_legal_source_route(
    source_id: UUID,
    request: Request,
    force: bool = Query(False, description="Delete even if a document is still being processed"),
    current_user: User = Depends(require_roles("ADMIN")),
    db: Session = Depends(get_db),
):
    """
    Permanently delete a legal source: all its editions and documents, their
    chunks in PostgreSQL, their vectors in Qdrant and the stored files.
    """
    from app.services.source_deletion import (
        SourceBusy,
        SourceNotFound,
        VectorStoreUnavailable,
        delete_legal_source,
    )

    try:
        result = delete_legal_source(
            db,
            source_id,
            actor_user_id=current_user.id,
            request_id=request_id_of(request),
            force=force,
        )
    except SourceNotFound:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Legal source not found.")
    except SourceBusy as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Still being processed: {exc}. Wait for it to finish, or delete with force.",
        )
    except VectorStoreUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="The vector database (Qdrant) could not be reached, so nothing was deleted. Try again when it is running.",
        )
    return SourceDeleteResponse(**vars(result))
