"""Request/response models for /api/v1/citations (SCRUM-26)."""

from typing import Any

from pydantic import BaseModel, Field


class CitationIn(BaseModel):
    ref: int = Field(ge=1, le=999)
    chunk_id: str | None = None
    source_title: str | None = None
    citation: str | None = None
    url: str | None = None


class CitationVerifyRequest(BaseModel):
    text: str = Field(min_length=1, max_length=100_000)
    citations: list[CitationIn] = Field(default_factory=list, max_length=100)


class VerifiedCitation(CitationIn):
    verification_status: str
    verification_issues: list[str] = Field(default_factory=list)
    verification_details: list[str] = Field(default_factory=list)


class CitationVerifyResponse(BaseModel):
    summary: dict[str, Any]
    citations: list[VerifiedCitation]
