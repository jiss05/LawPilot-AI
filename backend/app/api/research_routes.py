"""
POST /api/v1/research/search : hybrid legal retrieval without generation
(BRD §9 API list; SCRUM-16).

Every logged-in role may search: clients, lawyers and judge-support users
read the approved knowledge base (BRD FR-020). WHAT each caller may see is
decided by the backend from their roles, never by anything the client sends
(BRD §9: "never trust a client-provided user_id or role").
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.models.matter_member import MatterMember
from app.models.user import User
from app.rag.store_retriever import LegalSearchService, access_context_for
from app.rag.types import MetadataFilters
from app.schemas.research import (
    LocationResult,
    SearchRequest,
    SearchResponseModel,
    SearchResult,
    SourceResult,
)

router = APIRouter(prefix="/api/v1/research", tags=["Research"])

_service: LegalSearchService | None = None


def get_search_service() -> LegalSearchService:
    """One shared service (and so one loaded embedding model) per process."""
    global _service
    if _service is None:
        _service = LegalSearchService()
    return _service


def _filters(request: SearchRequest) -> MetadataFilters | None:
    if not (request.jurisdictions or request.source_types or request.trust_tiers):
        return None
    as_set = lambda values: frozenset(values) if values else None  # noqa: E731
    return MetadataFilters(
        jurisdictions=as_set(request.jurisdictions),
        source_types=as_set(request.source_types),
        trust_tiers=as_set(request.trust_tiers),
    )


@router.post("/search", response_model=SearchResponseModel)
def search(
    request: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
    service: LegalSearchService = Depends(get_search_service),
):
    matter_ids = frozenset(
        db.scalars(select(MatterMember.matter_id).where(MatterMember.user_id == current_user.id))
    )
    access = access_context_for(current_user, matter_ids)
    try:
        response = service.search(
            db, request.query, access=access, filters=_filters(request), top_k=request.top_k
        )
    except RuntimeError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Search is temporarily unavailable. Please try again shortly.",
        )

    results = []
    for chunk in response.results:
        meta, src = chunk.metadata, chunk.source
        results.append(SearchResult(
            chunk_id=chunk.chunk_id,
            text=chunk.text,
            score=round(chunk.score, 6),
            channels=list(chunk.channels),
            source=SourceResult(
                source_id=src.source_id,
                source_title=src.source_title,
                source_type=src.source_type,
                publisher=src.publisher,
                url=src.url,
                jurisdiction=src.jurisdiction,
                trust_tier=src.trust_tier,
                document_id=src.document_id,
                version_id=UUID(meta["version_id"]) if meta.get("version_id") else None,
                version_label=meta.get("version_label"),
                published_at=meta.get("published_at"),
                citation=src.citation,
            ),
            location=LocationResult(
                section_ref=src.section_ref,
                page_start=meta.get("page_start"),
                page_end=meta.get("page_end"),
                heading_path=meta.get("heading_path") or [],
            ),
        ))
    return SearchResponseModel(
        query=request.query,
        results=results,
        vector_candidates=response.vector_candidates,
        keyword_candidates=response.keyword_candidates,
        degraded=response.degraded,
        took_ms=response.took_ms,
    )
