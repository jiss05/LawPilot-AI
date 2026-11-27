"""
Legal drafts API (SCRUM-24: Implement legal draft generation and review).

    POST /api/v1/drafts/generate               Lawyer Agent drafts from case facts + sources
    GET  /api/v1/drafts                        drafts I can see (?status= filter)
    GET  /api/v1/drafts/{id}                   one draft
    PUT  /api/v1/drafts/{id}                   edit (new version, back to "draft")
    GET  /api/v1/drafts/{id}/versions          version history
    POST /api/v1/drafts/{id}/review            author submits for approval -> "reviewed"
    POST /api/v1/drafts/{id}/approve           authorized reviewer approves -> "approved"
    POST /api/v1/drafts/{id}/request-changes   reviewer sends back        -> "draft"
    POST /api/v1/drafts/{id}/export            .docx of an approved draft  -> "exported"

Acceptance criteria:
  * Lawyers can generate editable legal drafts      -> generate, PUT
  * Drafts can be saved and retrieved               -> draft_documents, GET
  * Draft versions are maintained                   -> draft_versions, /versions
  * Generated drafts are marked as requiring human review
                                                    -> requires_human_review in every
                                                       response; export watermark
  * Only authorized reviewers can approve drafts    -> _can_approve(): a lawyer other than
                                                       the author who owns the matter or has
                                                       `review`/`admin` matter permission
  * Approval and export actions are audited         -> draft.approved, draft.changes_requested,
                                                       draft.exported audit events
Citations are re-verified against the stored sources (SCRUM-26) on every
edit and before approval; a draft with failed citations cannot be approved.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from io import BytesIO
from uuid import UUID

from docx import Document
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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
    DraftReviewDecisionRequest,
    DraftUpdateRequest,
    DraftVersionResponse,
)
from app.services.audit_service import record_audit
from app.verification.citations import verify_citations
from app.verification.store import load_stored_sources

REVIEWER_PERMISSIONS = ("review", "admin")

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


def _can_approve(db: Session, draft: DraftDocument, user: User) -> bool:
    """An authorized reviewer: a lawyer, not the author, with review rights on the matter."""
    if draft.owner_user_id == user.id:
        return False  # nobody approves their own draft
    if "LAWYER" not in permissions.roles_of(user):
        return False
    matter = db.get(Matter, draft.matter_id)
    if matter is None:
        return False
    if matter.owner_user_id == user.id:
        return True
    member = db.scalar(
        select(MatterMember).where(
            MatterMember.matter_id == matter.id,
            MatterMember.user_id == user.id,
        )
    )
    return member is not None and member.permission in REVIEWER_PERMISSIONS


def _respond(db: Session, draft: DraftDocument, user: User) -> DraftResponse:
    response = DraftResponse.model_validate(draft)
    return response.model_copy(update={"can_approve": _can_approve(db, draft, user)})


def _reverify_citations(db: Session, draft: DraftDocument, user: User):
    """Re-check the draft's [n] citations against the stored legal sources."""
    citations = [dict(c) for c in (draft.citations or []) if isinstance(c, dict)]
    stored = load_stored_sources(
        db,
        [c.get("chunk_id") for c in citations],
        user_id=user.id,
        roles=permissions.roles_of(user),
    )
    report = verify_citations(draft.content, citations, stored)
    draft.citations = report.annotate(citations)
    return report


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

    return _respond(db, draft, current_user)


@router.get("/", response_model=list[DraftResponse])
def list_drafts(
    status_filter: str | None = Query(default=None, alias="status"),
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
    if status_filter:
        statement = statement.where(DraftDocument.status == status_filter)

    return [_respond(db, d, current_user) for d in db.scalars(statement).all()]


@router.get("/{draft_id}", response_model=DraftResponse)
def get_draft(
    draft_id: UUID,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _respond(db, _get_draft(db, draft_id, current_user), current_user)


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
    draft.approved_at = None
    draft.approved_by_user_id = None

    # The lawyer may have changed or added [n] references.
    report = _reverify_citations(db, draft, current_user)

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
            "citations_failed": report.failed_count,
        },
        request_id=request_id_of(request),
    )

    db.commit()
    db.refresh(draft)

    return _respond(db, draft, current_user)


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

    return _respond(db, draft, current_user)


def _require_reviewer(db: Session, draft: DraftDocument, user: User) -> None:
    if not _can_approve(db, draft, user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=(
                "Only an authorized reviewer can approve this draft. Reviewers are "
                "lawyers other than the author who own the matter or have review "
                "permission on it."
            ),
        )


@router.post("/{draft_id}/approve", response_model=DraftResponse)
def approve_draft(
    draft_id: UUID,
    request: Request,
    body: DraftReviewDecisionRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_lawyer(current_user)

    draft = _get_draft(db, draft_id, current_user)
    _require_reviewer(db, draft, current_user)

    if draft.status != "reviewed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only drafts submitted for review by their author can be approved.",
        )

    report = _reverify_citations(db, draft, current_user)
    if report.has_failures:
        db.commit()  # keep the refreshed verification results
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "This draft has citations that could not be verified against the "
                "stored legal sources. Ask the author to correct them before approval."
            ),
        )

    draft.status = "approved"
    draft.approved_at = datetime.now(timezone.utc)
    draft.approved_by_user_id = current_user.id
    draft.review_notes = body.notes if body else None

    record_audit(
        db,
        actor_user_id=current_user.id,
        action="draft.approved",
        target_type="draft_document",
        target_id=draft.id,
        metadata={"version": draft.version, "author_id": str(draft.owner_user_id)},
        request_id=request_id_of(request),
    )

    db.commit()
    db.refresh(draft)

    return _respond(db, draft, current_user)


@router.post("/{draft_id}/request-changes", response_model=DraftResponse)
def request_changes(
    draft_id: UUID,
    request: Request,
    body: DraftReviewDecisionRequest | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    _require_lawyer(current_user)

    draft = _get_draft(db, draft_id, current_user)
    _require_reviewer(db, draft, current_user)

    if draft.status != "reviewed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Only drafts awaiting review can be sent back.",
        )

    draft.status = "draft"
    draft.reviewed_at = None
    draft.review_notes = body.notes if body else None

    record_audit(
        db,
        actor_user_id=current_user.id,
        action="draft.changes_requested",
        target_type="draft_document",
        target_id=draft.id,
        metadata={"version": draft.version},
        request_id=request_id_of(request),
    )

    db.commit()
    db.refresh(draft)

    return _respond(db, draft, current_user)


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

    if draft.status not in ("approved", "exported"):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The draft must be approved by an authorized reviewer before export.",
        )

    document = Document()
    document.add_heading(draft.title, level=1)

    document.add_paragraph(
        "DRAFT - Requires professional verification",
        style="Subtitle",
    )
    if draft.approved_at is not None:
        document.add_paragraph(
            f"Approved by a reviewing advocate on {draft.approved_at:%d %B %Y} (version {draft.version})."
        )

    for line in draft.content.splitlines():
        document.add_paragraph(line)

    if draft.citations:
        document.add_heading("Sources and Citations", level=2)

        for citation in draft.citations:
            if isinstance(citation, dict):
                if citation.get("verification_status") == "not_cited":
                    continue
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
