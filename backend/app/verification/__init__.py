"""Citation verification (SCRUM-26)."""

from app.verification.citations import (
    ISSUE_INVALID_REFERENCE,
    ISSUE_MISSING_LOCATOR,
    ISSUE_QUOTE_MISMATCH,
    ISSUE_SOURCE_INACTIVE,
    ISSUE_SOURCE_MISMATCH,
    ISSUE_SOURCE_NOT_FOUND,
    STATUS_FAILED,
    STATUS_NOT_CITED,
    STATUS_VERIFIED,
    VerificationReport,
    stored_sources_from_retrieved,
    verify_citations,
)

__all__ = [
    "ISSUE_INVALID_REFERENCE",
    "ISSUE_MISSING_LOCATOR",
    "ISSUE_QUOTE_MISMATCH",
    "ISSUE_SOURCE_INACTIVE",
    "ISSUE_SOURCE_MISMATCH",
    "ISSUE_SOURCE_NOT_FOUND",
    "STATUS_FAILED",
    "STATUS_NOT_CITED",
    "STATUS_VERIFIED",
    "VerificationReport",
    "stored_sources_from_retrieved",
    "verify_citations",
]
