
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


class DraftCitation(BaseModel):
    ref: int | None = None
    chunk_id: str | None = None
    source_title: str | None = None
    citation: str | None = None
    url: str | None = None
    page_number: int | None = None
    section_ref: str | None = None
    # SCRUM-26: verified | failed | not_cited | unverified
    verification_status: str = "unverified"
    verification_issues: list[str] = Field(default_factory=list)
    verification_details: list[str] = Field(default_factory=list)


class DraftGenerateRequest(BaseModel):
    matter_id: UUID
    title: str = Field(min_length=1, max_length=255)
    document_type: str = Field(min_length=1, max_length=100)
    case_facts: str = Field(min_length=20)


class DraftUpdateRequest(BaseModel):
    title: str = Field(min_length=1, max_length=255)
    content: str = Field(min_length=1)


class DraftReviewDecisionRequest(BaseModel):
    notes: str | None = Field(default=None, max_length=4000)


class DraftResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    matter_id: UUID
    owner_user_id: UUID
    title: str
    content: str
    citations: list[DraftCitation] = Field(default_factory=list)
    status: str
    version: int
    reviewed_at: datetime | None = None
    approved_by_user_id: UUID | None = None
    approved_at: datetime | None = None
    review_notes: str | None = None
    exported_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
    # Set per caller: may this user approve the draft?
    can_approve: bool = False

    @computed_field
    @property
    def requires_human_review(self) -> bool:
        """Every AI draft needs human approval before it can be relied on."""
        return self.status not in ("approved", "exported")

    @computed_field
    @property
    def invalid_references(self) -> list[int]:
        """[n] references in the text that match no citation (SCRUM-26)."""
        from app.verification.citations import referenced_numbers

        known = {c.ref for c in self.citations if c.ref is not None}
        return [n for n in referenced_numbers(self.content) if n not in known]

    @computed_field
    @property
    def citations_verified(self) -> bool:
        cited = [c for c in self.citations if c.verification_status != "not_cited"]
        return (
            bool(cited)
            and all(c.verification_status == "verified" for c in cited)
            and not self.invalid_references
        )


class DraftVersionResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    draft_id: UUID
    version: int
    title: str
    content: str
    edited_by_user_id: UUID
    created_at: datetime
