
from __future__ import annotations

import re
from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID

from docx import Document
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.assistant_routes import _make_retriever, get_orchestrator
from app.api.dependencies import get_current_user
from app.core.request_id import request_id_of
from app.db.session import get_db
from app.models.draft_document import DraftDocument
from app.models.draft_version import DraftVersion
from app.models.matter import Matter
from app.models.matter_member import MatterMember
from app.models.user import User
from app.orchestration import permissions
from app.orchestration.state import STATUS_COMPLETED
from app.schemas.drafts import (
    DraftGenerateRequest,
    DraftResponse,
    DraftUpdateRequest,
    DraftVersionResponse,
)
from app.services.audit_service import record_audit

router = APIRouter(prefix="/api/v1/drafts", tags=["Drafts"])


def _require_lawyer(user: User) -> None:
    if "LAWYER" not in permissions.roles_of(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only lawyers can perform this action.",
        )


def _matter_access(
    db: Session,
    matter: Matter,
    user: User,
    *,
    write: bool = False,
) -> None:
    # The matter owner has implicit access.
    if matter.owner_user_id == user.id:
        return

    member = db.scalar(
        select(MatterMember).where(
            MatterMember.matter_id == matter.id,
            MatterMember.user_id == user.id,
        )
    )

    if member is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )

    if write and member.permission not in ("write", "admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Write permission is required for this matter.",
        )


def _get_matter(
    db: Session,
    matter_id: UUID,
    user: User,
    *,
    write: bool = False,
) -> Matter:
    matter = db.get(Matter, matter_id)

    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Matter not found.",
        )

    _matter_access(db, matter, user, write=write)
    return matter


def _get_draft(
    db: Session,
    draft_id: UUID,
    user: User,
) -> DraftDocument:
    draft = db.get(DraftDocument, draft_id)

    if draft is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found.",
        )

    # The draft owner can always access their own draft.
    if draft.owner_user_id == user.id:
        return draft

    matter = db.get(Matter, draft.matter_id)

    if matter is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Draft not found.",
        )

    _matter_access(db, matter, user)
    return draft


def _require_draft_owner(draft: DraftDocument, user: User) -> None:
    if draft.owner_user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only the lawyer who created this draft can modify it.",
        )


def _record_version(
    db: Session,
    draft: DraftDocument,
    user: User,
) -> None:
    db.add(
        DraftVersion(
            draft_id=draft.id,
            version=draft.version,
            title=draft.title,
            content=draft.content,
            edited_by_user_id=user.id,
        )
    )


@router.post("/generate", response_model=DraftResponse)
def generate_draft(
    body: DraftGenerateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    orchestrator=Depends(get_orchestrator),
):
    _require_lawyer(current_user)

    matter = _get_matter(
        db,
        body.matter_id,
        current_user,
        write=True,
    )

    if matter.status != "active":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Drafts can only be generated for active matters.",
        )

    prompt = f"""
Prepare a formal legal document draft.

Document type: {body.document_type}
Requested title: {body.title}

Matter details:
Matter title: {matter.title}
Jurisdiction: {matter.jurisdiction}
Court: {matter.court or "Not specified"}
Matter reference: {matter.matter_reference or "Not specified"}

Case facts supplied by the lawyer:
{body.case_facts}

Instructions:
1. Use only the legal sources retrieved from the knowledge base.
2. Do not invent statutes, case law, legal provisions, citations, facts,
   dates, parties, or court orders.
3. Do not present unsupported legal claims as established facts.
4. Use clear placeholders such as [INSERT DATE] or [VERIFY FACT]
   wherever required information is missing.
5. Structure the document professionally with suitable headings.
6. Clearly identify the output as a draft requiring lawyer verification.
7. Include source citations for supported legal authorities.
8. If the available evidence is insufficient, explain this rather
   than inventing legal authorities.
"""

    request_id = request_id_of(request)

    state = orchestrator.run(
        message=prompt,
        roles=list(permissions.roles_of(current_user)),
        user_id=str(current_user.id),
        requested_agent="lawyer",
        request_id=request_id,
        retriever=_make_retriever(db, current_user),
    )

    if state.get("status") != STATUS_COMPLETED:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={
                "message": "The Lawyer Agent could not complete a sufficiently supported draft.",
                "status": state.get("status"),
                "warnings": state.get("warnings", []),
            },
        )

    answer = (state.get("answer") or "").strip()
    citations = state.get("citations") or []

    if not answer or not citations:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Draft generation requires an answer supported by legal citations.",
        )

    draft = DraftDocument(
        matter_id=matter.id,
        owner_user_id=current_user.id,
        title=body.title,
        content=answer,
        citations=citations,
        status="draft",
        version=1,
    )

    db.add(draft)
    db.flush()

    _record_version(db, draft, current_user)

    record_audit(
        db,
        actor_user_id=current_user.id,
        action="draft.created",
        target_type="draft_document",
        target_id=draft.id,
        metadata={
            "matter_id": str(matter.id),
            "version": 1,
        },
        request_id=request_id,
    )

    db.commit()
    db.refresh(draft)

    return draft


@router.get("/", response_model=list[DraftResponse])
def list_drafts(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    statement = (
        select(DraftDocument)
        .join(Matter, Matter.id == DraftDocument.matter_id)
        .outerjoin(
            MatterMember,
            MatterMember.matter_id == Matter.id,
        )
        .where(
            (DraftDocument.owner_user_id == current_user.id)
            | (Matter.owner_user_id == current_user.id)
            | (MatterMember.user_id == current_user.id)
        )
        .distinct()
        .order_by(DraftDocument.updated_at.desc())
    )

    return list(db.scalars(statement).all())


@router.get("/{draft_id}", response_model=DraftResponse)
def get_draft(
    draft_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _get_draft(db, draft_id, current_user)


@router.put("/{draft_id}", response_model=DraftResponse)
def update_draft(
    draft_id: UUID,
    body: DraftUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_lawyer(current_user)

    draft = _get_draft(db, draft_id, current_user)
    _require_draft_owner(draft, current_user)

    if draft.status == "exported" or draft.exported_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An exported draft cannot be edited.",
        )

    old_version = draft.version

    draft.title = body.title
    draft.content = body.content
    draft.version += 1
    draft.status = "draft"
    draft.reviewed_at = None

    _record_version(db, draft, current_user)

    record_audit(
        db,
        actor_user_id=current_user.id,
        action="draft.updated",
        target_type="draft_document",
        target_id=draft.id,
        metadata={
            "previous_version": old_version,
            "new_version": draft.version,
        },
        request_id=request_id_of(request),
    )

    db.commit()
    db.refresh(draft)

    return draft


@router.get(
    "/{draft_id}/versions",
    response_model=list[DraftVersionResponse],
)
def list_draft_versions(
    draft_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    draft = _get_draft(db, draft_id, current_user)

    statement = (
        select(DraftVersion)
        .where(DraftVersion.draft_id == draft.id)
        .order_by(DraftVersion.version.desc())
    )

    return list(db.scalars(statement).all())


@router.post("/{draft_id}/review", response_model=DraftResponse)
def review_draft(
    draft_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_lawyer(current_user)

    draft = _get_draft(db, draft_id, current_user)
    _require_draft_owner(draft, current_user)

    if draft.status != "draft":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only drafts can be reviewed.",
        )

    draft.status = "reviewed"
    draft.reviewed_at = datetime.now(timezone.utc)

    record_audit(
        db,
        actor_user_id=current_user.id,
        action="draft.self_reviewed",
        target_type="draft_document",
        target_id=draft.id,
        metadata={"version": draft.version},
        request_id=request_id_of(request),
    )

    db.commit()
    db.refresh(draft)

    return draft


@router.post("/{draft_id}/export")
def export_draft(
    draft_id: UUID,
    request: Request,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_lawyer(current_user)

    draft = _get_draft(db, draft_id, current_user)
    _require_draft_owner(draft, current_user)

    if draft.status not in ("reviewed", "exported"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Review the draft yourself before exporting it.",
        )

    document = Document()
    document.add_heading(draft.title, level=1)

    document.add_paragraph(
        "DRAFT - Requires professional verification",
        style="Subtitle",
    )

    for line in draft.content.splitlines():
        document.add_paragraph(line)

    if draft.citations:
        document.add_heading("Sources and Citations", level=2)

        for citation in draft.citations:
            if isinstance(citation, dict):
                source_title = citation.get("source_title") or "Source"
                citation_text = citation.get("citation") or ""
                url = citation.get("url") or ""

                paragraph = document.add_paragraph()
                paragraph.add_run(f"{source_title}: ").bold = True
                paragraph.add_run(citation_text)

                if url:
                    paragraph.add_run(f" ({url})")

    buffer = BytesIO()
    document.save(buffer)
    buffer.seek(0)

    if draft.status != "exported":
        draft.status = "exported"
        draft.exported_at = datetime.now(timezone.utc)

        record_audit(
            db,
            actor_user_id=current_user.id,
            action="draft.exported",
            target_type="draft_document",
            target_id=draft.id,
            metadata={"version": draft.version},
            request_id=request_id_of(request),
        )

        db.commit()

    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", draft.title).strip("_")
    filename = f"{safe_title or 'legal_draft'}.docx"

    return StreamingResponse(
        iter([buffer.getvalue()]),
        media_type=(
            "application/vnd.openxmlformats-officedocument."
            "wordprocessingml.document"
        ),
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"'
        },
    )
