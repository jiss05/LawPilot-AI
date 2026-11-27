"""
Citation verification (SCRUM-26).

Checks every citation in a generated answer or draft against the legal
sources stored in the knowledge base, so a user can see which references
are supported and which are not.

    text with [1], [2] ... ─┐
    citations list ─────────┼─► verify_citations() ─► VerificationReport
    stored sources ─────────┘      (one CitationCheck per citation)

Acceptance criteria:
  * Citations are checked against stored legal sources -> each citation's
    chunk_id must exist in `stored_sources` (loaded from the database), be
    from an active edition, and match the stored source title.
  * Invalid source references are flagged  -> ISSUE_SOURCE_NOT_FOUND for an
    unknown chunk, ISSUE_INVALID_REFERENCE for a [n] in the text that no
    citation backs, ISSUE_SOURCE_MISMATCH when the title differs.
  * Missing locators are identified        -> ISSUE_MISSING_LOCATOR when the
    stored source has no section, page or citation string.
  * Quote mismatches are detected          -> ISSUE_QUOTE_MISMATCH when text in
    quotation marks next to [n] does not appear in source n.
  * Failed citations are not displayed as verified -> a citation is
    STATUS_VERIFIED only when it is used in the text AND has no issue;
    anything else is STATUS_FAILED or STATUS_NOT_CITED, and the report's
    `verified` flag is True only when nothing failed.

The verifier is deterministic (no model call), so it cannot be talked into
approving a citation.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

STATUS_VERIFIED = "verified"
STATUS_FAILED = "failed"
STATUS_NOT_CITED = "not_cited"

ISSUE_SOURCE_NOT_FOUND = "source_not_found"
ISSUE_SOURCE_INACTIVE = "source_inactive"
ISSUE_SOURCE_MISMATCH = "source_mismatch"
ISSUE_INVALID_REFERENCE = "invalid_reference"
ISSUE_MISSING_LOCATOR = "missing_locator"
ISSUE_QUOTE_MISMATCH = "quote_mismatch"

ISSUE_MESSAGES = {
    ISSUE_SOURCE_NOT_FOUND: "The cited source is not in the stored legal sources.",
    ISSUE_SOURCE_INACTIVE: "The cited source edition is no longer active.",
    ISSUE_SOURCE_MISMATCH: "The cited source title does not match the stored source.",
    ISSUE_INVALID_REFERENCE: "The text refers to a source number that does not exist.",
    ISSUE_MISSING_LOCATOR: "The citation has no section, page or other locator.",
    ISSUE_QUOTE_MISMATCH: "A quotation attributed to this source does not appear in it.",
}

# [1]  [1, 2]  [1,2,3]
_REF_RE = re.compile(r"\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\]")
# "quoted text" or “quoted text” of a useful length.
_QUOTE_RE = re.compile(r"[\"“]([^\"“”]{12,600})[\"”]")
_SENTENCE_END_RE = re.compile(r"(?<=[.!?])\s+")
_NON_WORD_RE = re.compile(r"[^0-9a-z]+")


@dataclass
class CitationCheck:
    ref: int | None
    chunk_id: str | None
    status: str
    cited_in_text: bool
    issues: list[str] = field(default_factory=list)
    details: list[str] = field(default_factory=list)

    def as_fields(self) -> dict[str, Any]:
        return {
            "verification_status": self.status,
            "verification_issues": list(self.issues),
            "verification_details": list(self.details),
        }


@dataclass
class VerificationReport:
    checks: list[CitationCheck]
    invalid_refs: list[int] = field(default_factory=list)
    unattributed_quotes: list[str] = field(default_factory=list)
    # Provisions/Acts the text names that no source contains (provisions.py).
    unsupported_mentions: list[str] = field(default_factory=list)

    @property
    def verified_count(self) -> int:
        return sum(1 for c in self.checks if c.status == STATUS_VERIFIED)

    @property
    def failed_count(self) -> int:
        return sum(1 for c in self.checks if c.status == STATUS_FAILED)

    @property
    def verified(self) -> bool:
        """True only if at least one citation verified and nothing failed."""
        return (
            self.verified_count > 0
            and self.failed_count == 0
            and not self.invalid_refs
            and not self.unattributed_quotes
            and not self.unsupported_mentions
        )

    @property
    def has_failures(self) -> bool:
        return bool(self.failed_count or self.invalid_refs or self.unattributed_quotes
                    or self.unsupported_mentions)

    def annotate(self, citations: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        """Copy of `citations` with verification fields added (same order)."""
        out = []
        for citation, check in zip(citations, self.checks):
            out.append({**dict(citation), **check.as_fields()})
        return out

    def summary(self) -> dict[str, Any]:
        return {
            "verified": self.verified,
            "verified_count": self.verified_count,
            "failed_count": self.failed_count,
            "not_cited_count": sum(1 for c in self.checks if c.status == STATUS_NOT_CITED),
            "invalid_references": list(self.invalid_refs),
            "unattributed_quotes": len(self.unattributed_quotes),
            "unsupported_mentions": list(self.unsupported_mentions),
        }


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def normalise(text: str | None) -> str:
    """Lower-case, strip accents/punctuation and collapse spaces for matching."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = text.replace("’", "'").replace("‘", "'")
    text = _NON_WORD_RE.sub(" ", text.lower())
    return " ".join(text.split())


def referenced_numbers(text: str) -> list[int]:
    """Every [n] reference in the text, in order of first appearance."""
    seen: list[int] = []
    for match in _REF_RE.finditer(text or ""):
        for part in match.group(1).split(","):
            n = int(part.strip())
            if n not in seen:
                seen.append(n)
    return seen


def _quotes_with_refs(text: str) -> list[tuple[str, list[int]]]:
    """Quotations and the [n] references in the same sentence."""
    results: list[tuple[str, list[int]]] = []
    for sentence in _SENTENCE_END_RE.split(text or ""):
        quotes = [q.strip() for q in _QUOTE_RE.findall(sentence)]
        if not quotes:
            continue
        refs = referenced_numbers(sentence)
        for quote in quotes:
            results.append((quote, refs))
    return results


def _has_locator(stored: Mapping[str, Any]) -> bool:
    return bool(
        (stored.get("section_ref") or "").strip()
        or stored.get("page_number") is not None
        or (stored.get("citation") or "").strip()
    )


def _titles_match(cited: str | None, stored: str | None) -> bool:
    if not cited or not stored:
        return True  # nothing to compare
    a, b = normalise(cited), normalise(stored)
    return a == b or a in b or b in a


def stored_sources_from_retrieved(sources: Iterable[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    """
    Index retrieved sources by chunk id.

    Retrieved sources come straight from the stored knowledge base (only
    active editions are searchable), so they are the stored record for
    answers produced in the same request.
    """
    out: dict[str, dict[str, Any]] = {}
    for src in sources or []:
        chunk_id = src.get("chunk_id")
        if chunk_id:
            out[str(chunk_id)] = {
                "text": src.get("text") or "",
                "source_title": src.get("source_title"),
                "citation": src.get("citation"),
                "section_ref": src.get("section_ref"),
                "page_number": src.get("page_number"),
                "active": src.get("active", True),
            }
    return out


# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def verify_citations(
    text: str,
    citations: list[Mapping[str, Any]],
    stored_sources: Mapping[str, Mapping[str, Any]],
) -> VerificationReport:
    """
    Verify `citations` used in `text` against `stored_sources`.

    `citations` entries carry `ref` (the [n] number) and `chunk_id`;
    `stored_sources` maps chunk_id -> {text, source_title, citation,
    section_ref, page_number, active}.
    """
    text = text or ""
    refs_in_text = referenced_numbers(text)
    by_ref = {c.get("ref"): c for c in citations if c.get("ref") is not None}

    # Quotations: which source numbers each one is attributed to.
    quote_failures: dict[int, list[str]] = {}
    unattributed: list[str] = []
    all_texts = [normalise(s.get("text")) for s in stored_sources.values()]
    for quote, refs in _quotes_with_refs(text):
        nq = normalise(quote)
        if not nq:
            continue
        backed = [r for r in refs if r in by_ref]
        if backed:
            found = any(
                nq in normalise((stored_sources.get(str(by_ref[r].get("chunk_id"))) or {}).get("text"))
                for r in backed
            )
            if not found:
                for r in backed:
                    quote_failures.setdefault(r, []).append(quote[:120])
        elif not any(nq in t for t in all_texts):
            unattributed.append(quote[:120])

    checks: list[CitationCheck] = []
    for citation in citations:
        ref = citation.get("ref")
        chunk_id = str(citation["chunk_id"]) if citation.get("chunk_id") else None
        cited = ref in refs_in_text
        issues: list[str] = []
        details: list[str] = []

        stored = stored_sources.get(chunk_id) if chunk_id else None
        if stored is None:
            issues.append(ISSUE_SOURCE_NOT_FOUND)
        else:
            if stored.get("active") is False:
                issues.append(ISSUE_SOURCE_INACTIVE)
            if not _titles_match(citation.get("source_title"), stored.get("source_title")):
                issues.append(ISSUE_SOURCE_MISMATCH)
            if not _has_locator(stored):
                issues.append(ISSUE_MISSING_LOCATOR)

        if ref in quote_failures:
            issues.append(ISSUE_QUOTE_MISMATCH)
            details.extend(f'Not found in source: "{q}"' for q in quote_failures[ref])

        details = [ISSUE_MESSAGES[i] for i in issues if i != ISSUE_QUOTE_MISMATCH] + details

        if not cited:
            status = STATUS_NOT_CITED
        elif issues:
            status = STATUS_FAILED
        else:
            status = STATUS_VERIFIED

        checks.append(CitationCheck(ref, chunk_id, status, cited, issues, details))

    invalid = [n for n in refs_in_text if n not in by_ref]

    from app.verification.provisions import unsupported_mentions

    missing = unsupported_mentions(text, stored_sources.values())
    return VerificationReport(checks=checks, invalid_refs=invalid, unattributed_quotes=unattributed,
                              unsupported_mentions=missing)
