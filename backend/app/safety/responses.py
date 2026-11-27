"""
Safe response handling (SCRUM-27).

Decides, for every assistant answer, whether it may be presented as a
reliable answer, and what the user must be told when it may not.

Acceptance criteria:
  * Unsupported questions are handled appropriately -> out-of-scope and
    no-evidence answers are marked unreliable with a plain notice
    (orchestrator rejects / safe fallback, then assess_reliability).
  * Conflicting sources are identified   -> detect_conflicts(): the same
    provision of the same source retrieved with materially different text
    (e.g. two editions), reported with both references.
  * Model and retrieval failures return understandable messages -> the
    messages below, used by the orchestrator and agents.
  * Stack traces and secrets are not exposed -> app.safety.redaction and the
    global handlers in app.main.
  * Failed results are not presented as reliable answers -> `reliable` is
    True only for a completed answer whose citations all verified and whose
    sources do not conflict.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass, field
from typing import Any, Iterable, Mapping

from app.verification.citations import VerificationReport, normalise

RETRIEVAL_UNAVAILABLE_MESSAGE = (
    "The legal knowledge base could not be searched just now, so I cannot "
    "give a source-backed answer. Please try again in a few minutes. If the "
    "problem continues, contact the administrator with the request ID."
)

# Shown instead of an answer when the uploaded legal documents do not cover
# the question (the model said so, or its answer was not grounded in them).
NO_ANSWER_MESSAGE = (
    "No answer available. The legal documents uploaded to LawPilot do not "
    "cover this question, so I cannot answer it without guessing. Please "
    "rephrase the question, or ask the administrator to upload the relevant "
    "law. For advice on a specific situation, consult a qualified advocate."
)

# Exact token the model is told to output when the sources do not answer.
NO_ANSWER_TOKEN = "NO_ANSWER_AVAILABLE"

# Similarity below which two texts for the same provision "conflict".
CONFLICT_SIMILARITY = 0.6

_PROVISION_RE = re.compile(
    r"(?i)\b(section|sec\.?|s\.|article|art\.?|rule|order|regulation|clause)\s*(\d+[a-z]?)"
)


@dataclass
class Reliability:
    reliable: bool
    notice: str | None = None
    reasons: list[str] = field(default_factory=list)


def _provision_key(src: Mapping[str, Any]) -> str | None:
    label = " ".join(str(src.get(k) or "") for k in ("section_ref", "citation"))
    match = _PROVISION_RE.search(label)
    if not match:
        return None
    kind = match.group(1).lower().rstrip(".")
    kind = {"sec": "section", "s": "section", "art": "article"}.get(kind, kind)
    return f"{kind} {match.group(2).lower()}"


def detect_conflicts(sources: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """
    Sources that state the same provision of the same source differently.

    Two retrieved chunks conflict when they come from the same source title,
    refer to the same provision (e.g. "Section 73"), and their texts are
    materially different. This typically means two editions (an amendment)
    or a disagreeing commentary, and the user must look at both.
    """
    groups: dict[tuple[str, str], list[tuple[int, Mapping[str, Any]]]] = {}
    for i, src in enumerate(sources or [], 1):
        key = _provision_key(src)
        title = normalise(src.get("source_title"))
        if key and title:
            groups.setdefault((title, key), []).append((i, src))

    conflicts = []
    for (_, provision), members in groups.items():
        if len(members) < 2:
            continue
        for a in range(len(members)):
            for b in range(a + 1, len(members)):
                (ra, sa), (rb, sb) = members[a], members[b]
                ta, tb = normalise(sa.get("text"))[:1500], normalise(sb.get("text"))[:1500]
                if not ta or not tb or ta == tb:
                    continue
                if ta in tb or tb in ta:  # one is an excerpt of the other
                    continue
                ratio = difflib.SequenceMatcher(None, ta, tb).ratio()
                if ratio < CONFLICT_SIMILARITY:
                    conflicts.append({
                        "refs": [ra, rb],
                        "provision": provision,
                        "source_title": sa.get("source_title"),
                        "similarity": round(ratio, 2),
                        "description": (
                            f"Sources [{ra}] and [{rb}] give different text for "
                            f"{provision} of {sa.get('source_title')}."
                        ),
                    })
    return conflicts


def conflict_note(conflicts: list[dict[str, Any]]) -> str:
    if not conflicts:
        return ""
    lines = ["", "", "Conflicting sources: the retrieved legal sources do not agree."]
    lines += [f"- {c['description']}" for c in conflicts]
    lines.append("Check which version applies before relying on this answer.")
    return "\n".join(lines)


def assess_reliability(
    *,
    status: str,
    citations: list[Mapping[str, Any]],
    verification: VerificationReport | None,
    conflicts: list[dict[str, Any]],
    warnings: Iterable[str] = (),
    safe_fallback: bool = False,
) -> Reliability:
    """Whether an answer may be shown as reliable, and the notice if not."""
    warnings = set(warnings)
    reasons: list[str] = []

    if status == "failed":
        return Reliability(False, "This request could not be completed. Nothing here should be relied on.", ["failed"])
    if status == "rejected":
        return Reliability(False, "This question is outside what LawPilot can answer, so no legal answer was given.", ["unsupported"])
    if status == "forbidden":
        return Reliability(False, "You do not have access to that assistant.", ["forbidden"])

    if "retrieval_unavailable" in warnings:
        reasons.append("retrieval_unavailable")
    if warnings & {"model_unavailable", "model_timeout", "model_bad_response"}:
        reasons.append("model_unavailable")
    if safe_fallback:
        reasons.append("no_supporting_sources")
    if not citations and not safe_fallback:
        reasons.append("no_citations")
    unsupported = list(getattr(verification, "unsupported_mentions", []) or [])
    if unsupported:
        reasons.append("unsupported_provisions")
    if verification is not None and (
        verification.failed_count or verification.invalid_refs or verification.unattributed_quotes
    ):
        reasons.append("citation_verification_failed")
    if citations and verification is not None and verification.verified_count == 0 and not verification.has_failures:
        reasons.append("citations_not_used")
    if conflicts:
        reasons.append("conflicting_sources")
    if status == "degraded" and not reasons:
        reasons.append("degraded")

    if not reasons:
        return Reliability(True, None, [])

    notices = {
        "retrieval_unavailable": "The legal knowledge base could not be searched, so this answer is not source-backed.",
        "model_unavailable": "The AI model was unavailable, so this answer may be incomplete.",
        "no_supporting_sources": "No supporting legal source was found for this question.",
        "no_citations": "This answer cites no legal source.",
        "unsupported_provisions": (
            "This answer names law that is not in the retrieved sources ("
            + ", ".join(unsupported[:6]) + ("…" if len(unsupported) > 6 else "")
            + "); it may be inaccurate or invented. The knowledge base may not cover this question."
        ),
        "citation_verification_failed": "Some citations could not be verified against the stored legal sources; check the flagged citations before relying on them.",
        "citations_not_used": "The answer does not refer to any of the retrieved sources.",
        "conflicting_sources": "The retrieved sources conflict with each other; check which applies.",
        "degraded": "This answer was produced with limited information.",
    }
    text = " ".join(notices[r] for r in reasons) + " Do not rely on it without independent verification."
    return Reliability(False, text, reasons)
