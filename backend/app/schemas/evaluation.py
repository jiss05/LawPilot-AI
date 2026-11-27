"""Models for the admin evaluation dashboard and answer feedback (SCRUM-29)."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field


class EvaluationReportSummary(BaseModel):
    name: str
    created_at: datetime
    provider: str | None = None
    model: str | None = None
    passed: bool
    metrics: dict[str, Any]
    checks: dict[str, bool]
    criteria: dict[str, Any]
    cases_total: int
    cases_passed: int


class EvaluationReport(EvaluationReportSummary):
    cases: list[dict[str, Any]]


class RuntimeStats(BaseModel):
    days: int
    total_runs: int
    by_status: dict[str, int]
    errors_by_code: dict[str, int]
    by_prompt_version: dict[str, int]
    avg_duration_ms: int | None
    p95_duration_ms: int | None


class FeedbackItem(BaseModel):
    rating: int
    issue_type: str | None
    comment: str | None
    created_at: datetime


class FeedbackSummary(BaseModel):
    total: int
    average_rating: float | None
    by_rating: dict[str, int]
    by_issue_type: dict[str, int]
    recent: list[FeedbackItem]


IssueType = Literal[
    "incorrect", "unsupported_citation", "incomplete", "not_neutral", "unclear", "other"
]


class FeedbackCreateRequest(BaseModel):
    message_id: UUID
    rating: int = Field(ge=1, le=5)
    issue_type: IssueType | None = None
    comment: str | None = Field(default=None, max_length=2000)


class FeedbackCreateResponse(BaseModel):
    id: UUID
    message_id: UUID
    rating: int
