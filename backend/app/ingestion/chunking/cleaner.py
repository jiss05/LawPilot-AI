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
    an "ARRANGEMENT OF SECTIONS" table of        find_table_of_contents_pages()
    contents before the Act itself (India
    Code PDFs): section titles without text
    amendment footnotes at the bottom of a      split_footnotes()
    page ("2. Subs. by Act 3 of 1951 ...")
    that would otherwise look like sections

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
      | (\d{1,2}\s?\[)?\d{1,4}[A-Z]{0,3}\.\s*(?=[A-Z(\["'])  # 73. / 73.Compensation / 2[19A. (inserted by amendment)
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
# 4. Table of contents ("ARRANGEMENT OF SECTIONS")
# ---------------------------------------------------------------------------
# India Code PDFs start with several pages that list every section title:
#     73. Compensation for loss or damage caused by breach of contract.
# Chunked as-is, every section would appear twice: once as a bare title.
# These pages run from the "ARRANGEMENT OF SECTIONS" heading up to the page
# where the Act itself begins ("ACT NO. 9 OF 1872", "BE it enacted ...").
_TOC_START_RE = re.compile(r"^\s*(ARRANGEMENT\s+OF\s+(SECTIONS|RULES|REGULATIONS|CLAUSES)|TABLE\s+OF\s+CONTENTS|CONTENTS)\s*$",
                           re.IGNORECASE | re.MULTILINE)
_BODY_START_RE = re.compile(r"(\bACT\s+NO\.?\s*\d+|\bBE\s+it\s+enacted\b|\bit\s+is\s+hereby\s+enacted\b|^\s*WHEREAS\b)",
                            re.IGNORECASE | re.MULTILINE)


def find_table_of_contents_pages(pages_text: list[str]) -> set[int]:
    """
    Return the indexes of table-of-contents pages. Only removes something
    when BOTH the TOC heading and the start of the Act body are found;
    otherwise nothing is touched (safe for documents without a TOC).
    """
    first_quarter = max(1, len(pages_text) // 4 + 1)
    toc_start = next((i for i, t in enumerate(pages_text[:first_quarter]) if _TOC_START_RE.search(t)), None)
    if toc_start is None:
        return set()
    body_start = next((i for i in range(toc_start, len(pages_text)) if _BODY_START_RE.search(pages_text[i])), None)
    if body_start is None or body_start == toc_start:
        return set()
    return set(range(toc_start, body_start))


# ---------------------------------------------------------------------------
# 5. Amendment footnotes
# ---------------------------------------------------------------------------
# Official Indian Acts record their amendment history in numbered footnotes
# at the bottom of each page:
#     2. Subs. by Act 3 of 1951, s. 3 and Sch., for "except Part B States."
#     3. The words "except ..." omitted by Act 34 of 2019, s. 95 (w.e.f. 31-10-2019).
# They start with "2." just like Section 2, so they must be taken out of the
# body text BEFORE structure detection. They are kept (not thrown away):
# each page's footnotes are stored with the chunks of that page.
_NUMBERED_LINE_RE = re.compile(r"^\s*(\d{1,3})\.\s*\S")
# Words that appear in amendment / editorial footnotes of Indian Acts:
#   "Subs. by Act 3 of 1951", "Ins. by", "rep. by", "omitted by", "w.e.f.",
#   "See s. 138, infra.", "Cf. s. 238", "As to ...", "(9 of 1890)", "ibid."
_FOOTNOTE_VOCAB_RE = re.compile(
    r"(\b(Subs|Ins|Rep|subs|ins|rep)\.|[Oo]mitted|[Ii]nserted|[Ss]ubstituted|[Rr]epealed|[Rr]enumbered"
    r"|[Aa]mended|w\.e\.f\.|by\s+(the\s+)?(Act|Ord\.|Ordinance|A\.\s?O\.|Regulation|Notification)\b"
    r"|Gazette|[Dd]eclared\s+in\s+force|[Ee]xtended\s+to|Adaptation|\b[Vv]ide\b|\b[Ss]ee\b"
    r"|\b(infra|supra|ibid)\b|\bC\.?f\.|\bAs\s+to\b|Statement\s+of\s+Objects"
    r"|\b[Ss]s?\.\s?\d|\(\d+\s+of\s+\d{4}\))"
)
# Footnotes are numbered 1, 2, 3 ... on each page; a block starting higher
# than this is not a footnote block (e.g. "239. [...] Rep. by s. 73" is a
# repealed SECTION whose text happens to use footnote-like words).
MAX_FIRST_FOOTNOTE_NUMBER = 15


def _is_footnote_start(lines: list[str], index: int) -> bool:
    if not _NUMBERED_LINE_RE.match(lines[index]):
        return False
    window = " ".join(lines[index:index + 3])  # a footnote's vocabulary may wrap to the next line
    return bool(_FOOTNOTE_VOCAB_RE.search(window))


def split_footnotes(lines: list[str]) -> tuple[list[str], list[str]]:
    """
    Split one page into (body lines, footnote lines).

    The footnote block is the bottom part of the page that starts with a
    numbered line using amendment vocabulary, and whose numbered lines run
    1, 2, 3 ... without gaps (footnote numbering restarts on every page). Only the lower half of the page is searched,
    so a numbered body paragraph near the top is never mistaken for one.
    """
    content_indexes = [i for i, line in enumerate(lines) if line.strip()]
    if not content_indexes:
        return lines, []
    lower_half_start = content_indexes[len(content_indexes) // 2]
    for i in range(lower_half_start, len(lines)):
        if not _is_footnote_start(lines, i):
            continue
        numbers = [int(m.group(1)) for line in lines[i:] if (m := _NUMBERED_LINE_RE.match(line))]
        consecutive = all(b == a + 1 for a, b in zip(numbers, numbers[1:]))
        if numbers[0] <= MAX_FIRST_FOOTNOTE_NUMBER and consecutive:
            return lines[:i], [line for line in lines[i:] if line.strip()]
    return lines, []


# ---------------------------------------------------------------------------
# Putting it together
# ---------------------------------------------------------------------------
@dataclass
class CleanedPage:
    page_number: int | None
    paragraphs: list[str]
    method: ExtractionMethod
    ocr_confidence: float | None = None
    # Amendment footnotes removed from this page's body (kept as metadata).
    footnotes: list[str] = field(default_factory=list)
    # True for table-of-contents pages (their paragraphs are empty).
    is_table_of_contents: bool = False

    @property
    def text(self) -> str:
        return "\n\n".join(self.paragraphs)


@dataclass
class CleaningReport:
    """Statistics saved in ingestion_jobs.counts (numbers only, no text)."""

    header_footer_patterns: int = 0
    edge_lines_removed: int = 0
    hyphenations_fixed: int = 0
    toc_pages_removed: int = 0
    footnotes_separated: int = 0
    chars_before: int = 0
    chars_after: int = 0
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "header_footer_patterns": self.header_footer_patterns,
            "edge_lines_removed": self.edge_lines_removed,
            "hyphenations_fixed": self.hyphenations_fixed,
            "toc_pages_removed": self.toc_pages_removed,
            "footnotes_separated": self.footnotes_separated,
            "chars_before": self.chars_before,
            "chars_after": self.chars_after,
        }


# ---------------------------------------------------------------------------
# Watermarks and sections glued onto the previous line
# ---------------------------------------------------------------------------
# India Code PDFs carry a faint "IndiaCode" watermark that the text layer
# mixes into the middle of sentences ("As betweenIndiaCodethe principal").
_WATERMARK_RE = re.compile(r"India\s?Code(?!\s+of\b)")
# A new section sometimes starts on the same text line as the end of the
# previous one, separated only by a run of spaces:
#   "... may employ an agent.    184. Who may be an agent.—..."
_GLUED_SECTION_RE = re.compile(r"(?<=[.;:\]—-])\s{3,}(?=(\d{1,2}\s?\[)?\d{1,4}[A-Z]{0,3}\.\s*[A-Z(\[\"'])")


def remove_watermarks(line: str) -> str:
    # Replaced by a space (not removed) so the spacing around it survives
    # for split_glued_sections; extra spaces are harmless later on.
    return _WATERMARK_RE.sub(" ", line) if "ndia" in line else line


def split_glued_sections(lines: list[str]) -> list[str]:
    """Put a section that starts mid-line onto its own line."""
    out: list[str] = []
    for line in lines:
        out.extend(_GLUED_SECTION_RE.split(line)[::2] if _GLUED_SECTION_RE.search(line) else [line])
    return [re.sub(r" {2,}", " ", part).strip() if part.strip() else "" for part in out if part is not None]


def clean_pages(pages: list[PageText], header_footer_min_ratio: float = 0.5) -> tuple[list[CleanedPage], CleaningReport]:
    """Clean every page; the page_number of each page is carried through unchanged."""
    report = CleaningReport()
    report.chars_before = sum(len(p.text) for p in pages)

    pages_lines = [normalise_characters(p.text).split("\n") for p in pages]
    repeated = find_repeated_edge_lines(pages_lines, header_footer_min_ratio)
    report.header_footer_patterns = len(repeated)

    toc_pages = find_table_of_contents_pages(["\n".join(lines) for lines in pages_lines])
    report.toc_pages_removed = len(toc_pages)

    cleaned: list[CleanedPage] = []
    for index, (page, lines) in enumerate(zip(pages, pages_lines)):
        if index in toc_pages:
            cleaned.append(CleanedPage(page.page_number, [], page.method, page.ocr_confidence,
                                       is_table_of_contents=True))
            continue
        lines, removed = _strip_edges(lines, repeated)
        report.edge_lines_removed += removed
        lines = split_glued_sections([remove_watermarks(line) for line in lines])
        lines, footnote_lines = split_footnotes(lines)
        footnotes = lines_to_paragraphs(footnote_lines) if footnote_lines else []
        report.footnotes_separated += len(footnotes)
        text, fixed = dehyphenate("\n".join(lines))
        report.hyphenations_fixed += fixed
        paragraphs = lines_to_paragraphs(text.split("\n"))
        cleaned.append(CleanedPage(page.page_number, paragraphs, page.method, page.ocr_confidence,
                                   footnotes=footnotes))

    report.chars_after = sum(len(p.text) for p in cleaned)
    return cleaned, report
