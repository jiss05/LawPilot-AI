"""
Hybrid retrieval over the REAL stores: Qdrant + PostgreSQL (SCRUM-16).

The rest of `app/rag/` (written in hybrid-search-v1) defines the retrieval
rules on in-memory data: authorization (filters.py), Reciprocal Rank Fusion
and de-duplication (ranking.py) and source provenance (sources.py). This
module feeds those same rules with data from the production databases.

    question
       │
       ├─► VECTOR channel   embed question ─► Qdrant nearest neighbours
       │                    (filters applied INSIDE Qdrant: visibility,
       │                     jurisdiction, source type, trust tier)
       │
       ├─► KEYWORD channel  PostgreSQL full-text search (GIN index)
       │                    (filters applied INSIDE the SQL query, plus
       │                     "edition is active" and "document is ready")
       │
       ├─► hydrate          one SQL query loads text, page, section, edition
       │                    and source for every candidate chunk id
       ├─► authorize again  filters.filter_search_hits (defence in depth:
       │                    nothing unauthorized or inactive can slip through)
       ├─► fuse             ranking.reciprocal_rank_fusion
       ├─► de-duplicate     ranking.deduplicate_chunks (same chunk id) and
       │                    deduplicate_by_content (same text in two files)
       └─► results          top_k chunks, each with full source information

Acceptance criteria:
  * Semantic and keyword searches return relevant results  -> both channels
  * Retrieval rankings are combined correctly              -> RRF (ranking.py)
  * Duplicate chunks are removed                           -> id + content de-dup
  * Metadata and authorization filters are applied         -> in Qdrant, in SQL, and again in Python
  * Relevant source information is returned                -> SourceInfo + version/page metadata

If Qdrant or the embedding model is down, search still answers from the
keyword channel and says so in `degraded` (BRD NFR-02: degrade gracefully).
"""

from __future__ import annotations

import hashlib
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from sqlalchemy import bindparam, text
from sqlalchemy.orm import Session

from app.ingestion.config import IngestionSettings, get_ingestion_settings
from app.ingestion.embeddings import EmbeddingProvider, get_embedding_provider
from app.ingestion.errors import ExtractionError
from app.ingestion.vector_store import QdrantVectorStore
from app.rag.filters import ADMIN_ROLE, filter_search_hits
from app.rag.ranking import DEFAULT_RRF_K, deduplicate_chunks, reciprocal_rank_fusion
from app.rag.sources import build_citation, require_source_info
from app.rag.types import (
    ACTIVE_VERSION_STATUS,
    READY_PROCESSING_STATUSES,
    VISIBILITY_INTERNAL,
    VISIBILITY_PRIVATE,
    VISIBILITY_PUBLIC,
    AccessContext,
    MetadataFilters,
    RetrievedChunk,
    SearchHit,
    SourceInfo,
)

logger = logging.getLogger(__name__)

# Roles that may read "internal" documents (professional users and admins).
INTERNAL_ROLES = frozenset({"admin", "lawyer", "judge"})


# ---------------------------------------------------------------------------
# Who is asking?
# ---------------------------------------------------------------------------
def access_context_for(user, matter_ids: frozenset[UUID] = frozenset()) -> AccessContext:
    """
    Build the AccessContext from a logged-in User. Role codes in the database
    are upper-case ("ADMIN"); the retrieval rules use lower-case names.
    """
    roles = frozenset(
        assignment.role.code.lower()
        for assignment in getattr(user, "role_assignments", [])
        if assignment.role is not None
    )
    return AccessContext(
        user_id=user.id,
        matter_ids=matter_ids,
        roles=roles,
        is_internal=bool(roles & INTERNAL_ROLES),
    )


def _can_see_all(access: AccessContext) -> bool:
    return ADMIN_ROLE in access.roles


# ---------------------------------------------------------------------------
# Vector channel (Qdrant)
# ---------------------------------------------------------------------------
def qdrant_filter(access: AccessContext, filters: MetadataFilters | None):
    """Translate access rules and metadata filters into a Qdrant filter."""
    from qdrant_client import models

    must: list = []
    if filters is not None:
        for key, values in (
            ("jurisdiction", filters.jurisdictions),
            ("source_type", filters.source_types),
            ("trust_tier", filters.trust_tiers),
        ):
            if values:
                must.append(models.FieldCondition(key=key, match=models.MatchAny(any=sorted(values))))

    if _can_see_all(access):
        return models.Filter(must=must) if must else None

    # Visible if ANY of these is true ("should" = OR in Qdrant).
    visible = [models.FieldCondition(key="visibility", match=models.MatchValue(value=VISIBILITY_PUBLIC))]
    if access.is_internal:
        visible.append(models.FieldCondition(key="visibility", match=models.MatchValue(value=VISIBILITY_INTERNAL)))
    visible.append(
        models.Filter(must=[
            models.FieldCondition(key="visibility", match=models.MatchValue(value=VISIBILITY_PRIVATE)),
            models.FieldCondition(key="uploaded_by", match=models.MatchValue(value=str(access.user_id))),
        ])
    )
    must.append(models.Filter(should=visible))
    return models.Filter(must=must)


# ---------------------------------------------------------------------------
# Keyword channel (PostgreSQL full-text search)
# ---------------------------------------------------------------------------
# Turns the question into an OR-query of its word stems:
#   "Can I claim compensation for delay?" -> 'claim' | 'compens' | 'delay'
# ('can', 'i', 'for' are stop words and disappear.) An OR-query is used
# because a plain AND-query would demand that EVERY word appears in a chunk.
_TSQUERY = """
    to_tsquery('simple', coalesce(array_to_string(ARRAY(
        SELECT quote_literal(lexeme)
        FROM unnest(tsvector_to_array(to_tsvector('english', :query))) AS lexeme
    ), ' | '), ''))
"""

_KEYWORD_SQL = f"""
    WITH q AS (SELECT {_TSQUERY} AS query)
    SELECT c.id AS chunk_id,
           ts_rank_cd(to_tsvector('english', c.text), q.query, 32) AS score
    FROM document_chunks c
    JOIN knowledge_documents d ON d.id = c.knowledge_document_id
    JOIN source_versions v ON v.id = c.source_version_id
    JOIN knowledge_sources s ON s.id = v.source_id
    CROSS JOIN q
    WHERE to_tsvector('english', c.text) @@ q.query
      AND v.status = :active
      AND d.processing_status IN :ready
      {{conditions}}
    ORDER BY score DESC, c.id
    LIMIT :limit
"""


def _sql_conditions(access: AccessContext, filters: MetadataFilters | None) -> tuple[str, dict[str, Any], list]:
    """WHERE clauses (and their bound parameters) for access and metadata."""
    clauses: list[str] = []
    params: dict[str, Any] = {}
    expanding: list = []
    if filters is not None:
        for column, name, values in (
            ("s.jurisdiction", "jurisdictions", filters.jurisdictions),
            ("s.source_type", "source_types", filters.source_types),
            ("s.trust_tier", "trust_tiers", filters.trust_tiers),
        ):
            if values:
                clauses.append(f"{column} IN :{name}")
                params[name] = sorted(values)
                expanding.append(bindparam(name, expanding=True))
    if not _can_see_all(access):
        visible = ["d.visibility = 'public'"]
        if access.is_internal:
            visible.append("d.visibility = 'internal'")
        visible.append("(d.visibility = 'private' AND d.uploaded_by = :user_id)")
        params["user_id"] = access.user_id
        clauses.append("(" + " OR ".join(visible) + ")")
    sql = "".join(f"\n      AND {c}" for c in clauses)
    return sql, params, expanding


def keyword_candidates(db: Session, query: str, access: AccessContext,
                       filters: MetadataFilters | None, limit: int) -> list[tuple[UUID, float]]:
    conditions, params, expanding = _sql_conditions(access, filters)
    statement = text(_KEYWORD_SQL.format(conditions=conditions)).bindparams(
        bindparam("ready", expanding=True), *expanding
    )
    rows = db.execute(statement, {
        "query": query,
        "active": ACTIVE_VERSION_STATUS,
        "ready": sorted(READY_PROCESSING_STATUSES),
        "limit": limit,
        **params,
    }).all()
    return [(row.chunk_id, float(row.score)) for row in rows]


# ---------------------------------------------------------------------------
# Hydration: candidate ids -> full chunk + source information
# ---------------------------------------------------------------------------
_HYDRATE_SQL = text("""
    SELECT c.id AS chunk_id, c.text, c.page_number, c.section_ref, c.chunk_index,
           c.metadata AS chunk_metadata,
           d.id AS document_id, d.filename, d.visibility, d.processing_status, d.uploaded_by,
           v.id AS version_id, v.version_label, v.published_at, v.status AS version_status,
           s.id AS source_id, s.title, s.source_type, s.publisher, s.canonical_url,
           s.jurisdiction, s.trust_tier
    FROM document_chunks c
    JOIN knowledge_documents d ON d.id = c.knowledge_document_id
    JOIN source_versions v ON v.id = c.source_version_id
    JOIN knowledge_sources s ON s.id = v.source_id
    WHERE c.id IN :ids
""").bindparams(bindparam("ids", expanding=True))


def _hydrate(db: Session, ids: list[UUID]) -> dict[UUID, Any]:
    if not ids:
        return {}
    return {row.chunk_id: row for row in db.execute(_HYDRATE_SQL, {"ids": ids}).all()}


def _hit(row, channel: str, rank: int, score: float) -> SearchHit:
    meta = row.chunk_metadata or {}
    source = SourceInfo(
        source_id=row.source_id,
        source_title=row.title,
        document_id=row.document_id,
        url=row.canonical_url,
        citation=build_citation(row.page_number, row.section_ref),
        page_number=row.page_number,
        section_ref=row.section_ref,
        publisher=row.publisher,
        source_type=row.source_type,
        jurisdiction=row.jurisdiction,
        trust_tier=row.trust_tier,
    )
    return SearchHit(
        chunk_id=row.chunk_id,
        score=score,
        rank=rank,
        channel=channel,
        text=row.text,
        source=source,
        visibility=row.visibility,
        matter_id=None,
        version_status=row.version_status,
        processing_status=row.processing_status,
        uploaded_by=row.uploaded_by,
        jurisdiction=row.jurisdiction,
        trust_tier=row.trust_tier,
        source_type=row.source_type,
        metadata={
            "page_start": row.page_number,
            "page_end": meta.get("page_end", row.page_number),
            "heading_path": meta.get("heading_path", []),
            "chunk_index": row.chunk_index,
            "filename": row.filename,
            "version_id": str(row.version_id),
            "version_label": row.version_label,
            "published_at": row.published_at.isoformat() if row.published_at else None,
            "content_hash": hashlib.sha256(row.text.encode("utf-8")).hexdigest(),
        },
    )


def _to_hits(rows: dict[UUID, Any], candidates: list[tuple[UUID, float]], channel: str) -> list[SearchHit]:
    hits = []
    for chunk_id, score in candidates:
        row = rows.get(chunk_id)
        if row is not None:  # a vector whose chunk was deleted is simply skipped
            hits.append(_hit(row, channel, len(hits) + 1, score))
    return hits


# ---------------------------------------------------------------------------
# Content de-duplication
# ---------------------------------------------------------------------------
_SPACE_RE = re.compile(r"\s+")


def deduplicate_by_content(chunks: list[RetrievedChunk]) -> list[RetrievedChunk]:
    """
    Two different chunk ids can hold the same text (e.g. the same Act was
    uploaded twice as two sources). Keep only the best-scoring copy.
    `chunks` must already be sorted best-first.
    """
    seen: set[str] = set()
    kept = []
    for chunk in chunks:
        key = _SPACE_RE.sub(" ", chunk.text.strip().lower())
        if key in seen:
            continue
        seen.add(key)
        kept.append(chunk)
    return kept


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------
@dataclass
class SearchResponse:
    results: list[RetrievedChunk]
    vector_candidates: int = 0
    keyword_candidates: int = 0
    degraded: list[str] = field(default_factory=list)  # channels that failed
    took_ms: int = 0


class LegalSearchService:
    def __init__(
        self,
        settings: IngestionSettings | None = None,
        *,
        provider: EmbeddingProvider | None = None,
        store: QdrantVectorStore | None = None,
        rrf_k: int = DEFAULT_RRF_K,
        candidate_multiplier: int = 4,
    ) -> None:
        self.settings = settings or get_ingestion_settings()
        self._provider = provider
        self.store = store or QdrantVectorStore(self.settings)
        self.rrf_k = rrf_k
        self.candidate_multiplier = candidate_multiplier

    @property
    def provider(self) -> EmbeddingProvider:
        if self._provider is None:
            self._provider = get_embedding_provider(self.settings)
        return self._provider

    def _vector_candidates(self, query: str, access: AccessContext,
                           filters: MetadataFilters | None, limit: int) -> list[tuple[UUID, float]]:
        vector = self.provider.embed_query(query)
        hits = self.store.search(vector, limit=limit, query_filter=qdrant_filter(access, filters))
        return [(hit.id, hit.score) for hit in hits]

    def search(
        self,
        db: Session,
        query: str,
        *,
        access: AccessContext,
        filters: MetadataFilters | None = None,
        top_k: int = 10,
    ) -> SearchResponse:
        started = time.perf_counter()
        response = SearchResponse(results=[])
        query = query.strip()
        if not query or top_k < 1:
            return response
        limit = top_k * self.candidate_multiplier

        try:
            vector = self._vector_candidates(query, access, filters, limit)
        except (ExtractionError, ValueError) as exc:
            logger.warning("Vector search unavailable, using keyword search only: %s", exc)
            vector, response.degraded = [], ["vector"]
        try:
            keyword = keyword_candidates(db, query, access, filters, limit)
        except Exception as exc:  # e.g. database error; never hide it completely
            logger.exception("Keyword search failed")
            db.rollback()
            keyword = []
            response.degraded.append("keyword")
            if "vector" in response.degraded:
                raise RuntimeError("Both retrieval channels failed.") from exc

        response.vector_candidates, response.keyword_candidates = len(vector), len(keyword)
        rows = _hydrate(db, list({cid for cid, _ in vector} | {cid for cid, _ in keyword}))

        channels = []
        for hits in (_to_hits(rows, vector, "vector"), _to_hits(rows, keyword, "keyword")):
            channels.append(filter_search_hits(hits, access=access, filters=filters))

        fused = deduplicate_chunks(reciprocal_rank_fusion(channels, k=self.rrf_k))
        results = deduplicate_by_content(fused)[:top_k]
        for chunk in results:
            require_source_info(chunk)
        response.results = results
        response.took_ms = round((time.perf_counter() - started) * 1000)
        return response
