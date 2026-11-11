"""Metadata and authorization filters for retrieval results.

Authorization rules (applied before results are returned)
---------------------------------------------------------
A chunk is visible to the caller only when all of the following hold:

1. ``version_status`` is ``active`` (superseded/withdrawn/failed are excluded).
2. ``processing_status`` is ``ready`` or ``completed``.
3. Visibility:
   - ``public``     → any authenticated caller
   - ``internal``   → callers with ``is_internal=True`` or an admin role
   - ``matter``     → caller is a member of ``matter_id`` (read+ permissions)
   - ``private``    → caller is the uploader, or has the ``admin`` role

Metadata filters (jurisdictions, trust tiers, source types, exact metadata
key/value matches) are applied in the same pass so unauthorized or out-of-scope
chunks never leave the retriever.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from app.rag.types import (
    ACTIVE_VERSION_STATUS,
    READY_PROCESSING_STATUSES,
    VISIBILITY_INTERNAL,
    VISIBILITY_MATTER,
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    AccessContext,
    IndexedChunk,
    MetadataFilters,
    SearchHit,
)


ADMIN_ROLE = "admin"


def _matches_metadata(chunk: IndexedChunk | SearchHit, filters: MetadataFilters) -> bool:
    if filters.jurisdictions is not None and chunk.jurisdiction not in filters.jurisdictions:
        return False
    if filters.trust_tiers is not None and chunk.trust_tier not in filters.trust_tiers:
        return False
    if filters.source_types is not None and chunk.source_type not in filters.source_types:
        return False
    if filters.metadata_equals:
        chunk_meta = chunk.metadata or {}
        for key, expected in filters.metadata_equals.items():
            if chunk_meta.get(key) != expected:
                return False
    return True


def is_authorized(chunk: IndexedChunk | SearchHit, access: AccessContext) -> bool:
    """Return True when the caller may see this chunk."""
    if chunk.version_status != ACTIVE_VERSION_STATUS:
        return False
    if chunk.processing_status not in READY_PROCESSING_STATUSES:
        return False

    visibility = chunk.visibility
    if visibility == VISIBILITY_PUBLIC:
        return True
    if visibility == VISIBILITY_INTERNAL:
        return access.is_internal or ADMIN_ROLE in access.roles
    if visibility == VISIBILITY_MATTER:
        if chunk.matter_id is None:
            return False
        return chunk.matter_id in access.matter_ids or ADMIN_ROLE in access.roles
    if visibility == VISIBILITY_PRIVATE:
        if ADMIN_ROLE in access.roles:
            return True
        return chunk.uploaded_by is not None and chunk.uploaded_by == access.user_id
    # Unknown visibility is denied by default.
    return False


def apply_metadata_filters(
    chunks: Sequence[IndexedChunk] | Iterable[IndexedChunk],
    filters: MetadataFilters | None,
) -> list[IndexedChunk]:
    """Filter an indexed corpus by metadata constraints."""
    if filters is None:
        return list(chunks)
    return [chunk for chunk in chunks if _matches_metadata(chunk, filters)]


def apply_access_filters(
    chunks: Sequence[IndexedChunk] | Iterable[IndexedChunk],
    access: AccessContext,
) -> list[IndexedChunk]:
    """Filter an indexed corpus by authorization rules."""
    return [chunk for chunk in chunks if is_authorized(chunk, access)]


def filter_search_hits(
    hits: Sequence[SearchHit],
    *,
    access: AccessContext,
    filters: MetadataFilters | None = None,
) -> list[SearchHit]:
    """Drop unauthorized / out-of-scope hits and re-rank remaining ones."""
    kept: list[SearchHit] = []
    for hit in hits:
        if not is_authorized(hit, access):
            continue
        if filters is not None and not _matches_metadata(hit, filters):
            continue
        kept.append(hit)

    # Preserve relative order, then assign fresh 1-based ranks.
    re_ranked: list[SearchHit] = []
    for index, hit in enumerate(kept, start=1):
        re_ranked.append(
            SearchHit(
                chunk_id=hit.chunk_id,
                score=hit.score,
                rank=index,
                channel=hit.channel,
                text=hit.text,
                source=hit.source,
                visibility=hit.visibility,
                matter_id=hit.matter_id,
                version_status=hit.version_status,
                processing_status=hit.processing_status,
                uploaded_by=hit.uploaded_by,
                jurisdiction=hit.jurisdiction,
                trust_tier=hit.trust_tier,
                source_type=hit.source_type,
                metadata=hit.metadata,
            )
        )
    return re_ranked


def filter_indexed_corpus(
    chunks: Sequence[IndexedChunk],
    *,
    access: AccessContext,
    filters: MetadataFilters | None = None,
) -> list[IndexedChunk]:
    """Apply auth then metadata filters to the searchable corpus."""
    authorized = apply_access_filters(chunks, access)
    return apply_metadata_filters(authorized, filters)
