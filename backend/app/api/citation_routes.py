"""
Citation verification API (SCRUM-26).

    POST /api/v1/citations/verify   check [n] citations in a text against the
                                    stored legal sources

Returns each citation with `verification_status` (verified | failed |
not_cited) and the issues found. Source text is never returned.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.user import User
from app.orchestration import permissions
from app.schemas.citations import CitationVerifyRequest, CitationVerifyResponse
from app.verification.citations import verify_citations
from app.verification.store import load_stored_sources

router = APIRouter(prefix="/api/v1/citations", tags=["Citations"])


@router.post("/verify", response_model=CitationVerifyResponse)
def verify(
    body: CitationVerifyRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    citations = [c.model_dump() for c in body.citations]
    stored = load_stored_sources(
        db,
        [c.get("chunk_id") for c in citations],
        user_id=current_user.id,
        roles=permissions.roles_of(current_user),
    )
    report = verify_citations(body.text, citations, stored)
    return CitationVerifyResponse(
        summary=report.summary(),
        citations=report.annotate(citations),
    )
