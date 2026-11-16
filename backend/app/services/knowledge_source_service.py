
import hashlib
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.config import get_ingestion_settings
from app.ingestion.pipeline import DocumentStatus
from app.models.knowledge_source import KnowledgeSource
from app.models.source_version import SourceVersion
from app.models.knowledge_document import KnowledgeDocument
from app.services.audit_service import record_audit


def _document_directory() -> Path:
    """
    Folder where uploaded files are saved (default: backend/legal_documents/).

    Sprint 2 fix: this used to be hard-coded here while the extraction step
    looked in a different folder, so extraction could not find uploads.
    Both now read the same setting, INGESTION_STORAGE_DIR.
    """
    return get_ingestion_settings().storage_dir

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


def _validate_pdf(file_content: bytes) -> None:
    if len(file_content) > MAX_FILE_SIZE:
        raise ValueError("PDF file must not exceed 20 MB.")
    if not file_content.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF.")


def _store_edition(
    db: Session,
    *,
    source: KnowledgeSource,
    version_label: str | None,
    published_at,
    original_filename: str,
    file_content: bytes,
    uploaded_by,
    visibility: str,
) -> tuple[SourceVersion, KnowledgeDocument, Path]:
    """
    Save the file and add a new `pending` edition (source_versions row) plus
    its document row. Shared by the first upload of a source and by every
    later edition (SCRUM-18). Does not commit.
    """
    document_directory = _document_directory()
    document_directory.mkdir(parents=True, exist_ok=True)

    document_id = uuid.uuid4()
    stored_filename = f"{document_id}.pdf"
    file_path = document_directory / stored_filename
    content_hash = hashlib.sha256(file_content).hexdigest()

    safe_filename = original_filename.replace("\\", "/").split("/")[-1]
    safe_filename = safe_filename[:255]

    # The storage key is relative to the storage folder, so the folder can
    # move (or become cloud storage later) without changing database rows.
    storage_key = stored_filename

    file_path.write_bytes(file_content)

    version = SourceVersion(
        source_id=source.id,
        version_label=version_label,
        published_at=published_at,
        content_hash=content_hash,
        # "pending" until the ingestion pipeline has processed and checked it;
        # activation (app/ingestion/activation.py) then makes it "active".
        status="pending",
        raw_storage_key=storage_key,
    )
    db.add(version)
    db.flush()

    document = KnowledgeDocument(
        id=document_id,
        source_version_id=version.id,
        filename=safe_filename,
        file_type="application/pdf",
        storage_key=storage_key,
        sha256=content_hash,
        uploaded_by=uploaded_by,
        processing_status=DocumentStatus.UPLOADED,
        visibility=visibility,
    )
    db.add(document)
    return version, document, file_path


def register_legal_source(
    db: Session,
    *,
    title: str,
    source_type: str,
    jurisdiction: str,
    trust_tier: str,
    publisher: str | None,
    canonical_url: str | None,
    version_label: str | None,
    published_at,
    original_filename: str,
    file_content: bytes,
    uploaded_by,
    visibility: str = "public",
    request_id: str | None = None,
):
    """
    Register a legal source and its first edition (PDF document).

    Returns (source, document).
    """
    _validate_pdf(file_content)
    file_path = None
    try:
        source = KnowledgeSource(
            title=title,
            source_type=source_type,
            publisher=publisher,
            canonical_url=canonical_url,
            jurisdiction=jurisdiction,
            trust_tier=trust_tier,
        )
        db.add(source)
        db.flush()

        version, document, file_path = _store_edition(
            db, source=source, version_label=version_label, published_at=published_at,
            original_filename=original_filename, file_content=file_content,
            uploaded_by=uploaded_by, visibility=visibility,
        )
        record_audit(
            db, actor_user_id=uploaded_by, action="knowledge_source.created",
            target_type="knowledge_source", target_id=source.id, request_id=request_id,
            metadata={"version_id": str(version.id), "document_id": str(document.id),
                      "filename": document.filename, "sha256": document.sha256},
        )
        db.commit()
        db.refresh(source)

        # Return the document too: the API route needs its id to start
        # processing in the background.
        return source, document

    except Exception:
        db.rollback()
        if file_path is not None and file_path.exists():
            file_path.unlink()
        raise


def register_source_version(
    db: Session,
    *,
    source: KnowledgeSource,
    version_label: str | None,
    published_at,
    original_filename: str,
    file_content: bytes,
    uploaded_by,
    visibility: str = "public",
    request_id: str | None = None,
):
    """
    Add a NEW EDITION of an existing source (SCRUM-18), e.g. an amended Act.

    The current edition stays active and searchable until the new one has
    been fully processed; activation then supersedes it. Nothing is
    overwritten. Uploading a file identical to an existing edition of this
    source is refused, since it would not be a new version.

    Returns (version, document).
    """
    _validate_pdf(file_content)
    content_hash = hashlib.sha256(file_content).hexdigest()
    duplicate = db.scalar(
        select(SourceVersion).where(
            SourceVersion.source_id == source.id,
            SourceVersion.content_hash == content_hash,
            SourceVersion.status != "failed",
        )
    )
    if duplicate is not None:
        raise ValueError(
            f"This exact file is already registered as edition "
            f"'{duplicate.version_label or duplicate.id}' ({duplicate.status})."
        )

    file_path = None
    try:
        version, document, file_path = _store_edition(
            db, source=source, version_label=version_label, published_at=published_at,
            original_filename=original_filename, file_content=file_content,
            uploaded_by=uploaded_by, visibility=visibility,
        )
        record_audit(
            db, actor_user_id=uploaded_by, action="source_version.created",
            target_type="source_version", target_id=version.id, request_id=request_id,
            metadata={"source_id": str(source.id), "document_id": str(document.id),
                      "version_label": version_label, "filename": document.filename,
                      "sha256": document.sha256},
        )
        db.commit()
        db.refresh(version)
        return version, document
    except Exception:
        db.rollback()
        if file_path is not None and file_path.exists():
            file_path.unlink()
        raise


def get_legal_sources(db: Session):
    statement = (
        select(KnowledgeSource)
        .order_by(KnowledgeSource.created_at.desc())
    )

    return list(db.scalars(statement).all())


def get_legal_source(db: Session, source_id):
    statement = select(KnowledgeSource).where(
        KnowledgeSource.id == source_id
    )

    return db.scalar(statement)


def get_source_documents(db: Session, source_id):
    statement = (
        select(KnowledgeDocument)
        .join(
            SourceVersion,
            KnowledgeDocument.source_version_id == SourceVersion.id,
        )
        .where(SourceVersion.source_id == source_id)
        .order_by(KnowledgeDocument.uploaded_at.desc())
    )

    return list(db.scalars(statement).all())
