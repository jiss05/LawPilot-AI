
import hashlib
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.knowledge_source import KnowledgeSource
from app.models.source_version import SourceVersion
from app.models.knowledge_document import KnowledgeDocument


# backend/legal_documents/
DOCUMENT_DIRECTORY = (
    Path(__file__).resolve().parents[2] / "legal_documents"
)

MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


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
):
    """Register a legal source and its PDF document."""

    if len(file_content) > MAX_FILE_SIZE:
        raise ValueError("PDF file must not exceed 20 MB.")

    if not file_content.startswith(b"%PDF-"):
        raise ValueError("The uploaded file is not a valid PDF.")

    DOCUMENT_DIRECTORY.mkdir(parents=True, exist_ok=True)

    document_id = uuid.uuid4()
    stored_filename = f"{document_id}.pdf"
    file_path = DOCUMENT_DIRECTORY / stored_filename

    content_hash = hashlib.sha256(file_content).hexdigest()

    safe_filename = original_filename.replace("\\", "/").split("/")[-1]
    safe_filename = safe_filename[:255]

    storage_key = f"legal_documents/{stored_filename}"

    try:
        # Save the actual PDF file.
        file_path.write_bytes(file_content)

        # Create the legal source.
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

        # Create the source version.
        version = SourceVersion(
            source_id=source.id,
            version_label=version_label,
            published_at=published_at,
            content_hash=content_hash,
            status="active",
            raw_storage_key=storage_key,
        )

        db.add(version)
        db.flush()

        # Register PDF metadata.
        document = KnowledgeDocument(
            id=document_id,
            source_version_id=version.id,
            filename=safe_filename,
            file_type="application/pdf",
            storage_key=storage_key,
            sha256=content_hash,
            uploaded_by=uploaded_by,
            processing_status="pending",
            visibility="internal",
        )

        db.add(document)
        db.commit()
        db.refresh(source)

        return source

    except Exception:
        db.rollback()

        if file_path.exists():
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
