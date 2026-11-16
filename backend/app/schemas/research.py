"""Request/response models for POST /api/v1/research/search (SCRUM-16)."""

from uuid import UUID

from pydantic import BaseModel, Field


class SearchRequest(BaseModel):
    query: str = Field(min_length=2, max_length=1000, examples=["compensation for breach of contract"])
    top_k: int = Field(default=10, ge=1, le=50)
    # Optional metadata filters (BRD §10.2: jurisdiction, source type ...)
    jurisdictions: list[str] | None = Field(default=None, examples=[["India"]])
    source_types: list[str] | None = Field(default=None, examples=[["statute"]])
    trust_tiers: list[str] | None = Field(default=None, examples=[["official"]])


class SourceResult(BaseModel):
    source_id: UUID
    source_title: str
    source_type: str | None
    publisher: str | None
    url: str | None
    jurisdiction: str | None
    trust_tier: str | None
    document_id: UUID | None
    version_id: UUID | None
    version_label: str | None
    published_at: str | None
    citation: str | None  # e.g. "Section 73, p. 17"


class LocationResult(BaseModel):
    section_ref: str | None
    page_start: int | None
    page_end: int | None
    heading_path: list[str] = []


class SearchResult(BaseModel):
    chunk_id: UUID
    text: str
    score: float  # fused RRF score: higher = more relevant
    channels: list[str]  # which searches found it: "vector", "keyword" or both
    source: SourceResult
    location: LocationResult


class SearchResponseModel(BaseModel):
    query: str
    results: list[SearchResult]
    vector_candidates: int
    keyword_candidates: int
    degraded: list[str]  # channels that were unavailable (search still answered)
    took_ms: int
