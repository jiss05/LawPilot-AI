"""
Text cleaning and normalisation.

Acceptance criterion: "Extracted text is cleaned and normalized."

Raw PDF text is messy in predictable ways. This module fixes each problem
with a small, separately testable function, and works PAGE BY PAGE so the
page references from extraction are never lost.

    Problem in raw text                         Fix
    ------------------------------------------  -------------------------------
    "ﬁ" ligatures, non-breaking spaces,         normalise_characters()
    invisible characters, curly quotes
    the same header/footer on every page        find_repeated_edge_lines()
    ("THE GAZETTE OF INDIA ... 3")
    lone page numbers ("Page 3 of 42", "- 3 -") is_page_number_line()
    words split at line ends ("compen-\\nsation") dehyphenate()
    one paragraph broken into many short        lines_to_paragraphs()
    lines (PDFs store visual lines, not
    paragraphs)

What we deliberately DO NOT change: the words themselves, numbering such
as "73." / "(1)" / "(a)", dashes like "commencement.—(1)", and case. Legal
meaning lives in those details, and later the citation verifier must find
quotes in this text exactly.
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter
from dataclasses import dataclass, field

from app.ingestion.extraction_types import ExtractionMethod, PageText

# ---------------------------------------------------------------------------
# 1. Character normalisation
# ---------------------------------------------------------------------------
_REPLACEMENTS = {
    # ligatures produced by some PDF fonts
    "ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl",
    # unusual spaces -> normal space
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", " ": " ", " ": " ", " ": " ", " ": " ",
    " ": " ", "　": " ", "\t": " ",
    # invisible characters -> removed
    "​": "", "‌": "", "‍": "", "﻿": "", "­": "",
    # curly quotes -> straight quotes (makes exact quote matching reliable)
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    # hyphen look-alikes -> normal hyphen (en/em dashes are kept: they
    # carry meaning in statutes, e.g. "commencement.—(1)")
    "‐": "-", "‑": "-",
    "\r": "\n", "\f": "\n",
}
_REPLACE_RE = re.compile("|".join(map(re.escape, _REPLACEMENTS)))


def normalise_characters(text: str) -> str:
    """
    NFC normalisation joins a letter and a separate accent mark into one
    character, so the same word is always stored the same way. Then the
    replacement table above is applied.
    """
    text = unicodedata.normalize("NFC", text)
    return _REPLACE_RE.sub(lambda m: _REPLACEMENTS[m.group(0)], text)


# ---------------------------------------------------------------------------
# 2. Page numbers and running headers / footers
# ---------------------------------------------------------------------------
_PAGE_NUMBER_RE = re.compile(
    r"^(page\s*)?[-–—(\[]?\s*\d{1,4}\s*[-–—)\]]?(\s*(of|/)\s*\d{1,4})?$",
    re.IGNORECASE,
)
EDGE_LINES = 2  # how many lines at the top and bottom of a page we inspect
HEADER_MAX_CHARS = 100  # running headers/footers are short lines


def is_page_number_line(line: str) -> bool:
    """True for lines like '3', '- 3 -', 'Page 3', 'Page 3 of 42', '[3]'."""
    return bool(_PAGE_NUMBER_RE.match(line.strip()))


def _edge_key(line: str) -> str:
    """
    Make a comparable key for a header/footer line: lower-case, digits
    replaced by '#', spaces collapsed. So "THE GAZETTE OF INDIA  3" and
    "The Gazette of India 4" give the same key.
    """
    return re.sub(r"\s+", " ", re.sub(r"\d+", "#", line.strip().lower()))


def _edge_lines(lines: list[str]) -> list[str]:
    non_empty = [line for line in lines if line.strip()]
    return non_empty[:EDGE_LINES] + non_empty[-EDGE_LINES:]


def find_repeated_edge_lines(pages_lines: list[list[str]], min_ratio: float) -> set[str]:
    """
    Return the keys of lines that appear at the top or bottom of many pages.

    Needs at least 3 pages: with 1-2 pages we cannot tell a header from
    normal text, so nothing is removed.
    """
    if len(pages_lines) < 3:
        return set()
    counter: Counter[str] = Counter()
    for lines in pages_lines:
        counter.update({
            _edge_key(line)
            for line in _edge_lines(lines)
            # Never treat legal content as a header: "Section 5. ..." at the
            # top of every page differs only by its number, which the key
            # hides. Real running headers are also short.
            if len(line.strip()) <= HEADER_MAX_CHARS and not _STRUCTURAL_START_RE.match(line.strip())
        })
    threshold = max(3, min_ratio * len(pages_lines))
    return {key for key, count in counter.items() if count >= threshold and key}


def _strip_edges(lines: list[str], repeated: set[str]) -> tuple[list[str], int]:
    """Remove header/footer and page-number lines from the top/bottom only."""
    removed = 0
    lines = list(lines)
    for from_top in (True, False):
        checked = 0
        index = 0 if from_top else len(lines) - 1
        while 0 <= index < len(lines) and checked < EDGE_LINES:
            line = lines[index]
            if not line.strip():
                index += 1 if from_top else -1
                continue
            checked += 1
            if _edge_key(line) in repeated or is_page_number_line(line):
                lines.pop(index)
                removed += 1
                if not from_top:
                    index -= 1
                continue
            index += 1 if from_top else -1
    return lines, removed


# ---------------------------------------------------------------------------
# 3. Hyphenation and paragraph rebuilding
# ---------------------------------------------------------------------------
_HYPHEN_BREAK_RE = re.compile(r"([A-Za-z])-\n\s*([a-z])")


def dehyphenate(text: str) -> tuple[str, int]:
    """
    Join words split across lines: "compen-\\nsation" -> "compensation".
    Only when the next line starts with a lower-case letter, so line-ending
    dashes before a new sentence or clause are kept.
    """
    return _HYPHEN_BREAK_RE.subn(r"\1\2", text)


# Lines that always START a new paragraph, even without a blank line.
_STRUCTURAL_START_RE = re.compile(
    r"""^(
        (CHAPTER|PART|SCHEDULE)\b                       # CHAPTER VI, PART II
      | (Section|Sec\.|S\.)\s*\d                          # Section 73
      | \d{1,4}[A-Z]{0,3}\.\s                             # 73. / 12. (sections, paras)
      | \(\d{1,3}[A-Z]?\)\s                               # (1)
      | \([a-z]{1,4}\)\s                                  # (a) (iv)
      | (Explanation|Illustrations?|Exception|Provided)\b # explanations, provisos
    )""",
    re.VERBOSE,
)


def is_heading_line(line: str) -> bool:
    """Short ALL-CAPS line such as 'JUDGMENT' or 'FACTS OF THE CASE'."""
    stripped = line.strip()
    letters = [ch for ch in stripped if ch.isalpha()]
    return (
        2 <= len(letters)
        and len(stripped.split()) <= 10
        and sum(ch.isupper() for ch in letters) / len(letters) > 0.85
        and not stripped.endswith((",", ";"))
    )


def lines_to_paragraphs(lines: list[str]) -> list[str]:
    """
    Rebuild paragraphs from visual lines.

    A new paragraph starts when:
      * there is a blank line, or
      * the line starts with legal numbering ("73.", "(1)", "(a)", ...), or
      * the line is a heading, or follows a heading, or
      * the previous line ended a sentence AND was clearly shorter than a
        full line (the typical look of a paragraph's last line).
    Otherwise the line continues the current paragraph.
    """
    content = [line.strip() for line in lines]
    lengths = [len(line) for line in content if len(line) > 40]
    full_line = statistics.median(lengths) if lengths else 80

    paragraphs: list[list[str]] = []
    previous = ""
    for line in content:
        if not line:
            previous = ""
            if paragraphs and paragraphs[-1]:
                paragraphs.append([])
            continue
        starts_new = (
            not paragraphs
            or not paragraphs[-1]
            or _STRUCTURAL_START_RE.match(line)
            or is_heading_line(line)
            or is_heading_line(previous)
            or (previous.endswith((".", ":", ";", "?", "!", '."', ".'")) and len(previous) < 0.8 * full_line)
        )
        if starts_new and paragraphs and paragraphs[-1]:
            paragraphs.append([line])
        elif not paragraphs:
            paragraphs.append([line])
        else:
            paragraphs[-1].append(line)
        previous = line

    return [re.sub(r" {2,}", " ", " ".join(p)).strip() for p in paragraphs if p]


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------
@dataclass
class CleanedPage:
    page_number: int | None
    paragraphs: list[str]
    method: ExtractionMethod
    ocr_confidence: float | None = None

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


@dataclass
class CleaningReport:
    """Statistics saved in ingestion_jobs.counts (numbers only, no text)."""

    header_footer_patterns: int = 0
    edge_lines_removed: int = 0
    hyphenations_fixed: int = 0
    chars_before: int = 0
    chars_after: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "header_footer_patterns": self.header_footer_patterns,
            "edge_lines_removed": self.edge_lines_removed,
            "hyphenations_fixed": self.hyphenations_fixed,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
        }


def clean_pages(pages: list[PageText], header_footer_min_ratio: float = 0.5) -> tuple[list[CleanedPage], CleaningReport]:
    """Clean every page; the page_number of each page is carried through unchanged."""
    report = CleaningReport()
    report.chars_before = sum(len(p.text) for p in pages)

    pages_lines = [normalise_characters(p.text).split("\n") for p in pages]
    repeated = find_repeated_edge_lines(pages_lines, header_footer_min_ratio)
    report.header_footer_patterns = len(repeated)

    cleaned: list[CleanedPage] = []
    for page, lines in zip(pages, pages_lines):
        lines, removed = _strip_edges(lines, repeated)
        report.edge_lines_removed += removed
        text, fixed = dehyphenate("\n".join(lines))
        report.hyphenations_fixed += fixed
        paragraphs = lines_to_paragraphs(text.split("\n"))
        cleaned.append(CleanedPage(page.page_number, paragraphs, page.method, page.ocr_confidence))

    report.chars_after = sum(len(p.text) for p in cleaned)
    return cleaned, report
