
from datetime import date
from uuid import UUID

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user, require_roles
from app.db.session import get_db
from app.models.user import User
from app.schemas.knowledge_source import (
    KnowledgeSourceResponse,
    KnowledgeDocumentResponse,
)
from app.ingestion.tasks import process_uploaded_document
from app.services.knowledge_source_service import (
    register_legal_source,
    get_legal_sources,
    get_legal_source,
    get_source_documents,
)


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
    # FastAPI fills this in automatically (no default needed); it must come
    # first because Python does not allow a parameter without a default
    # after parameters that have one.
    background_tasks: BackgroundTasks,
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

