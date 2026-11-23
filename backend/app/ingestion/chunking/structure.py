"""
Legal structure detection.

Acceptance criterion: "Legal sections and paragraphs are preserved."

Each cleaned paragraph is labelled with WHAT it is, so the chunker can cut
along legal boundaries instead of at random character counts.

STATUTES (Acts, Rules, Regulations)            JUDGMENTS
-----------------------------------            ---------
CHAPTER VI  OF THE CONSEQUENCES ...            JUDGMENT / FACTS  (all-caps headings)
73. Compensation for loss ...   -> section     12. The appellant contends ... -> numbered paragraph
(1) ...                         -> subsection
(a) ...                         -> clause
Explanation.— / Illustration    -> explanation
Provided that ...               -> proviso

The same text "12. ..." means "Section 12" in an Act but "paragraph 12"
in a judgment, so the knowledge source's `source_type` decides the mode.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum

from app.ingestion.chunking.cleaner import CleanedPage, is_heading_line


class Mode(str, Enum):
    STATUTE = "statute"
    JUDGMENT = "judgment"


class BlockKind(str, Enum):
    CHAPTER = "chapter"          # CHAPTER VI / PART II / SCHEDULE
    HEADING = "heading"          # short all-caps line
    SECTION = "section"          # 73. ... (statute)
    NUMBERED_PARA = "numbered_paragraph"  # 12. ... (judgment)
    SUBSECTION = "subsection"    # (1)
    CLAUSE = "clause"            # (a), (iv)
    EXPLANATION = "explanation"  # Explanation / Illustration / Exception / Provided that
    PARAGRAPH = "paragraph"      # anything else

    @property
    def starts_unit(self) -> bool:
        """Kinds that begin a new legal unit (and so, normally, a new chunk)."""
        return self in {BlockKind.CHAPTER, BlockKind.HEADING, BlockKind.SECTION, BlockKind.NUMBERED_PARA}


@dataclass
class Block:
    text: str
    page_number: int | None
    kind: BlockKind
    label: str | None = None  # "Section 73", "Para 12", "Chapter VI", "(1)" ...


# "CHAPTER VI", "Part 2", "THE FIRST SCHEDULE". A number is required after
# Chapter/Part so that a sentence like "Part of the land ..." is not mistaken
# for a heading.
_CHAPTER_RE = re.compile(
    r"^(?:(CHAPTER|Chapter|PART|Part)\s+([IVXLCDM]+|\d+[A-Z]?)\b|(?:THE\s+[A-Z]+\s+)?(SCHEDULE)\b)"
)
# "73. Compensation ...", "73.Compensation ...", and "2[19A. Power to ..." -
# in official Acts a section inserted by an amendment is wrapped in a
# bracket preceded by its footnote number ("2[" = see footnote 2).
_SECTION_RE = re.compile(r"^(?:\d{1,2}\s?\[)?(?:(?:Section|Sec\.|S\.)\s*)?(\d{1,4}[A-Z]{0,3})\.\s*[-–—]?\s*(?=[A-Z(\[\"'])")
# "Section 10. What agreements ..." - the number must be followed by "." or a
# dash, so a sentence such as "Section 294A of the Indian Penal Code not
# affected" is NOT read as the start of Section 294A.
_EXPLICIT_SECTION_RE = re.compile(r"^(?:Section|Sec\.)\s+(\d{1,4}[A-Z]{0,3})\s*[.:\-–—]")
_NUMBERED_PARA_RE = re.compile(r"^(\d{1,4})\.\s+\S")
_SUBSECTION_RE = re.compile(r"^\((\d{1,3}[A-Z]?)\)\s")
_CLAUSE_RE = re.compile(r"^\(([a-z]{1,4})\)\s")
_EXPLANATION_RE = re.compile(r"^(Explanation(?:\s*\d+)?|Illustrations?|Exception(?:\s*\d+)?|Provided\b)")

_JUDGMENT_WORDS = ("judg", "case", "order", "decision", "ruling")


def mode_for_source_type(source_type: str | None) -> Mode:
    """'judgment', 'Supreme Court judgment', 'case law' -> JUDGMENT; anything else -> STATUTE."""
    value = (source_type or "").lower()
    return Mode.JUDGMENT if any(word in value for word in _JUDGMENT_WORDS) else Mode.STATUTE


def classify(paragraph: str, mode: Mode) -> tuple[BlockKind, str | None]:
    """Return (kind, label) for one cleaned paragraph."""
    if match := _CHAPTER_RE.match(paragraph):
        if match.group(3):
            return BlockKind.CHAPTER, "Schedule"
        return BlockKind.CHAPTER, f"{match.group(1).capitalize()} {match.group(2)}"

    if mode == Mode.STATUTE:
        if match := (_EXPLICIT_SECTION_RE.match(paragraph) or _SECTION_RE.match(paragraph)):
            return BlockKind.SECTION, f"Section {match.group(1)}"
    else:
        if match := _NUMBERED_PARA_RE.match(paragraph):
            return BlockKind.NUMBERED_PARA, f"Para {match.group(1)}"

    if match := _SUBSECTION_RE.match(paragraph):
        return BlockKind.SUBSECTION, f"({match.group(1)})"
    if match := _CLAUSE_RE.match(paragraph):
        return BlockKind.CLAUSE, f"({match.group(1)})"
    if _EXPLANATION_RE.match(paragraph):
        return BlockKind.EXPLANATION, None
    if is_heading_line(paragraph):
        return BlockKind.HEADING, paragraph.strip()[:80]
    return BlockKind.PARAGRAPH, None


def _section_number(label: str) -> int:
    return int(re.match(r"\D*(\d+)", label).group(1))


# Indian Acts do not have more than 999 sections, so a 4-digit "section
# number" is almost always a footnote marker glued onto the real number.
MAX_REAL_SECTION_NUMBER = 999


def _repair_glued_number(number: int, last_section: int) -> int | None:
    """
    Decide whether a section number is believable, fixing a common PDF
    artefact on the way: a footnote marker printed just before a section
    number gets glued to it ("¹151." is extracted as "1151.").

    Returns the (possibly repaired) number, or None if the line should be
    treated as an ordinary paragraph (lower than the previous section).
    Forward jumps are allowed: Acts skip repealed ranges (e.g. 76 to 123).
    """
    if number > MAX_REAL_SECTION_NUMBER:
        digits = str(number)
        candidates = [int(digits[cut:]) for cut in (1, 2) if len(digits) > cut]
        believable = [c for c in candidates if last_section <= c <= MAX_REAL_SECTION_NUMBER]
        return min(believable, key=lambda c: c - last_section) if believable else None
    return number if number >= last_section else None


def detect_structure(pages: list[CleanedPage], mode: Mode) -> list[Block]:
    """
    Turn cleaned pages into one ordered list of labelled blocks.

    Safety net for statutes: section numbers only go UP through an Act
    (19, 19A, 20 ...). A "section" whose number is lower than the previous
    one (e.g. a stray "3. ..." line, or a footnote the cleaner missed) is
    treated as an ordinary paragraph of the current section instead.
    Schedules restart their own numbering, so a Schedule heading resets it.
    """
    blocks: list[Block] = []
    last_section = 0
    for page in pages:
        for paragraph in page.paragraphs:
            kind, label = classify(paragraph, mode)
            if mode == Mode.STATUTE and kind == BlockKind.CHAPTER and label == "Schedule":
                last_section = 0
            if mode == Mode.STATUTE and kind == BlockKind.SECTION:
                number = _repair_glued_number(_section_number(label), last_section)
                if number is None:
                    kind, label = BlockKind.PARAGRAPH, None
                else:
                    label = "Section " + str(number) + re.sub(r"^\D*\d+", "", label)
                    last_section = number
            blocks.append(Block(paragraph, page.page_number, kind, label))
    return blocks
