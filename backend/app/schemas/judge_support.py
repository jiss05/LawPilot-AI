"""Request/response models for /api/v1/judge-support (SCRUM-25)."""

from typing import Any

from pydantic import BaseModel, Field


class CaseFactIn(BaseModel):
    text: str = Field(min_length=3, max_length=2000)
    # Where the fact comes from (exhibit, page, paragraph, witness ...).
    # Required: every fact in a brief must stay traceable to its source.
    source_ref: str = Field(min_length=1, max_length=300, examples=["Exhibit P-2, para 4"])
    date: str | None = Field(default=None, max_length=40, examples=["2024-03-12"])
    disputed: bool = False
    asserted_by: str | None = Field(default=None, max_length=200)


class PartyArgumentIn(BaseModel):
    text: str = Field(min_length=3, max_length=3000)
    source_ref: str | None = Field(default=None, max_length=300)


class PartyIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(min_length=1, max_length=100, examples=["Petitioner"])
    arguments: list[PartyArgumentIn] = Field(min_length=1, max_length=50)


class CaseBriefRequest(BaseModel):
    case_title: str = Field(min_length=1, max_length=300)
    case_number: str | None = Field(default=None, max_length=100)
    court: str | None = Field(default=None, max_length=200)
    question: str | None = Field(default=None, max_length=2000)
    facts: list[CaseFactIn] = Field(min_length=1, max_length=200)
    parties: list[PartyIn] = Field(min_length=2, max_length=6)
    use_knowledge_base: bool = True


class BriefFact(BaseModel):
    id: str
    text: str
    source_ref: str
    date: str | None = None
    date_iso: str | None = None
    disputed: bool = False
    asserted_by: str | None = None


class ChronologyEntry(BaseModel):
    date: str
    date_iso: str
    fact_id: str
    text: str
    source_ref: str
    disputed: bool = False


class DisputedIssue(BaseModel):
    id: str
    issue: str
    fact_ids: list[str] = Field(default_factory=list)
    source_refs: list[str] = Field(default_factory=list)
    basis: str  # "disputed_fact" | "model"


class PartyArgument(BaseModel):
    id: str
    text: str
    source_ref: str | None = None


class PartyArguments(BaseModel):
    party: str
    role: str
    arguments: list[PartyArgument]


class BriefSource(BaseModel):
    ref: int
    chunk_id: str | None = None
    source_title: str | None = None
    citation: str | None = None
    url: str | None = None
    verification_status: str | None = None
    verification_issues: list[str] = Field(default_factory=list)


class CaseBriefResponse(BaseModel):
    request_id: str | None
    case_title: str
    case_number: str | None = None
    court: str | None = None
    status: str                       # completed | degraded
    reliable: bool
    notice: str | None = None
    facts: list[BriefFact]
    chronology: list[ChronologyEntry]
    undated_fact_ids: list[str]
    disputed_issues: list[DisputedIssue]
    party_arguments: list[PartyArguments]
    neutral_summary: str
    legal_sources: list[BriefSource] = Field(default_factory=list)
    verification: dict[str, Any] = Field(default_factory=dict)
    conflicts: list[dict[str, Any]] = Field(default_factory=list)
    neutrality: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
    disclaimer: str
