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
_SECTION_RE = re.compile(r"^(?:(?:Section|Sec\.|S\.)\s*)?(\d{1,4}[A-Z]{0,3})\.\s*[-–—]?\s*(?=[A-Z(\[\"'])")
_EXPLICIT_SECTION_RE = re.compile(r"^(?:Section|Sec\.)\s+(\d{1,4}[A-Z]{0,3})\b")
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


def detect_structure(pages: list[CleanedPage], mode: Mode) -> list[Block]:
    """Turn cleaned pages into one ordered list of labelled blocks."""
    blocks: list[Block] = []
    for page in pages:
        for paragraph in page.paragraphs:
            kind, label = classify(paragraph, mode)
            blocks.append(Block(paragraph, page.page_number, kind, label))
    return blocks
