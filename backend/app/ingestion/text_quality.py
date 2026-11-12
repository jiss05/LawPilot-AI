"""
Decide whether natively extracted text is "good enough".

Acceptance criterion: "OCR is applied when normal text extraction is
insufficient."

"Insufficient" has two meanings for a PDF page:

1. TOO LITTLE TEXT - a scanned page is just a photo, so PyMuPDF finds
   0 characters. Some scans have a tiny printed stamp ("Page 3"), so we
   use a minimum character count instead of checking for exactly zero.

2. GARBLED TEXT - some PDFs (common with older Indian court PDFs that use
   legacy fonts) have text, but the font has no proper character map,
   so extraction returns junk such as "���" or private-use
   symbols. The characters exist but are meaningless. We measure what
   share of characters look like real text.

This is deliberately simple and explainable. It can be tuned through
`INGESTION_MIN_NATIVE_CHARS_PER_PAGE` and `INGESTION_MIN_TEXT_QUALITY_RATIO`.
"""

from __future__ import annotations

from dataclasses import dataclass

# Punctuation we expect in legal text: section signs, brackets, quotes ...
_ALLOWED_PUNCTUATION = set(".,;:!?'\"()[]{}-–—/\\&%$#@*+=<>|_§°•`~^‘’“”…₹")


@dataclass(frozen=True)
class TextAssessment:
    sufficient: bool
    reason: str | None  # "too_little_text" / "garbled_text" / None
    char_count: int
    quality_ratio: float


def quality_ratio(text: str) -> float:
    """
    Share (0..1) of non-space characters that look like real text.

    `str.isalnum()` is Unicode-aware, so Hindi (Devanagari) letters and
    digits also count as "real" characters, not only English.
    """
    visible = [ch for ch in text if not ch.isspace()]
    if not visible:
        return 0.0
    good = sum(1 for ch in visible if ch.isalnum() or ch in _ALLOWED_PUNCTUATION)
    return good / len(visible)


def assess_text(
    text: str,
    min_chars: int,
    min_quality_ratio: float,
) -> TextAssessment:
    """Return whether `text` is usable without OCR, and why not if it isn't."""
    char_count = sum(1 for ch in text if not ch.isspace())
    ratio = quality_ratio(text)

    if char_count < min_chars:
        return TextAssessment(False, "too_little_text", char_count, ratio)
    if ratio < min_quality_ratio:
        return TextAssessment(False, "garbled_text", char_count, ratio)
    return TextAssessment(True, None, char_count, ratio)
