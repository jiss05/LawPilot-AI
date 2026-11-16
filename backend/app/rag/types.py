"""Shared types for hybrid legal retrieval."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import UUID


# Document visibility values used by access-control filters.
VISIBILITY_PUBLIC = "public"
VISIBILITY_INTERNAL = "internal"
VISIBILITY_MATTER = "matter"
VISIBILITY_PRIVATE = "private"

ACTIVE_VERSION_STATUS = "active"
READY_PROCESSING_STATUSES = frozenset({"ready", "completed"})


@dataclass(frozen=True)
class SourceInfo:
    """Provenance attached to every retrieved chunk."""

    source_id: UUID
    source_title: str
    document_id: UUID | None = None
    url: str | None = None
    citation: str | None = None
    page_number: int | None = None
    section_ref: str | None = None
    publisher: str | None = None
    source_type: str | None = None
    jurisdiction: str | None = None
    trust_tier: str | None = None


@dataclass
class IndexedChunk:
    """Chunk available for vector and/or keyword retrieval."""

    chunk_id: UUID
    text: str
    source: SourceInfo
    embedding: list[float] | None = None
    visibility: str = VISIBILITY_PUBLIC
    matter_id: UUID | None = None
    version_status: str = ACTIVE_VERSION_STATUS
    processing_status: str = "completed"
    uploaded_by: UUID | None = None
    jurisdiction: str = "India"
    trust_tier: str = "primary"
    source_type: str = "statute"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SearchHit:
    """Single ranked hit from one retrieval channel."""

    chunk_id: UUID
    score: float
    rank: int
    channel: str
    text: str
    source: SourceInfo
    visibility: str = VISIBILITY_PUBLIC
    matter_id: UUID | None = None
    version_status: str = ACTIVE_VERSION_STATUS
    processing_status: str = "completed"
    uploaded_by: UUID | None = None
    jurisdiction: str = "India"
    trust_tier: str = "primary"
    source_type: str = "statute"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RetrievedChunk:
    """Final hybrid-retrieval result returned to agents."""

    chunk_id: UUID
    text: str
    score: float
    source: SourceInfo
    channels: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MetadataFilters:
    """Optional content filters applied before results are returned."""

    jurisdictions: frozenset[str] | None = None
    trust_tiers: frozenset[str] | None = None
    source_types: frozenset[str] | None = None
    metadata_equals: dict[str, Any] | None = None


@dataclass(frozen=True)
class AccessContext:
    """Caller identity used for authorization filtering."""

    user_id: UUID
    matter_ids: frozenset[UUID] = frozenset()
    roles: frozenset[str] = frozenset()
    is_internal: bool = False
