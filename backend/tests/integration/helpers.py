"""Build realistic knowledge-base data by running the real pipeline."""

from __future__ import annotations

import uuid
from pathlib import Path

from app.core.security import hash_password
from app.ingestion.pipeline import DocumentStatus
from app.ingestion.tasks import process_document
from app.models.knowledge_document import KnowledgeDocument
from app.models.knowledge_source import KnowledgeSource
from app.models.role import Role
from app.models.source_version import SourceVersion
from app.models.user import User
from app.models.user_role import UserRole

from tests.ingestion.helpers import make_statute_pdf


def make_user(db, role_code: str) -> User:
    role = db.query(Role).filter(Role.code == role_code).one_or_none()
    if role is None:
        role = Role(id=uuid.uuid4(), code=role_code)
        db.add(role)
        db.flush()
    user = User(
        email=f"{role_code.lower()}-{uuid.uuid4().hex[:8]}@lawpilot-demo.in",
        password_hash=hash_password("Passw0rd!123"),
        display_name=role_code.title(),
        is_active=True,
        email_verified=True,
    )
    db.add(user)
    db.flush()
    db.add(UserRole(user_id=user.id, role_id=role.id))
    db.flush()
    db.refresh(user)
    return user


def ingest_statute(
    db,
    settings,
    admin: User,
    *,
    title: str = "Sample Contract Act, 1872",
    source_type: str = "statute",
    visibility: str = "public",
    activate: bool = True,
    pdf: Path | None = None,
):
    """Register a source + edition + document, then run the real pipeline."""
    source = KnowledgeSource(title=title, source_type=source_type, jurisdiction="India",
                             trust_tier="official", publisher="Legislative Department",
                             canonical_url="https://www.indiacode.nic.in/example")
    db.add(source)
    db.flush()
    version = SourceVersion(source_id=source.id, version_label="As amended 2023",
                            content_hash=uuid.uuid4().hex, status="pending")
    db.add(version)
    db.flush()
    document_id = uuid.uuid4()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    stored = settings.storage_dir / f"{document_id}.pdf"
    if pdf is None:
        make_statute_pdf(stored)
    else:
        stored.write_bytes(pdf.read_bytes())
    document = KnowledgeDocument(
        id=document_id, source_version_id=version.id, filename="act.pdf", file_type="application/pdf",
        storage_key=stored.name, sha256="", uploaded_by=admin.id,
        processing_status=DocumentStatus.UPLOADED, visibility=visibility,
    )
    db.add(document)
    db.commit()

    import app.ingestion.chunk_pipeline as cp
    import app.ingestion.index_pipeline as ip
    from app.ingestion import pipeline as ep

    # Run each stage with the test settings (embedded Qdrant, hashing model).
    jobs = [
        ep.run_extraction(db, document.id, admin.id, settings=settings,
                          extractor=ep.DocumentExtractor(settings)),
    ]
    jobs.append(cp.run_chunking(db, document.id, admin.id, settings=settings))
    jobs.append(ip.run_indexing(db, document.id, admin.id, settings=settings))
    assert all(j.status == "completed" for j in jobs), [j.error_summary for j in jobs]

    if activate:  # what SCRUM-18 activation does
        version.status = "active"
        document.processing_status = "completed"
        db.commit()
    return source, version, document
