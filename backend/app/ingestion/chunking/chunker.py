"""
Chunking: divide a document into meaningful pieces.

Acceptance criteria:
  * "Documents are divided into meaningful chunks."
  * "Each chunk maintains its source and page references."

WHY CHUNK AT ALL?
Search returns chunks, not whole documents, and an answer cites a chunk.
A chunk should therefore be:
  * ONE legal idea (one section / one judgment paragraph), so a citation
    points at exactly what supports the answer,
  * not too big (an embedding of 20 pages means nothing in particular),
  * not too small ("(b) the seller;" alone has no meaning).

THE RULES, IN ORDER
1. Group blocks into UNITS: a unit starts at a Chapter, a heading, a
   statute section ("73. ...") or a numbered judgment paragraph ("12. ...")
   and includes the sub-sections, clauses, explanations and plain
   paragraphs that follow it.
2. A unit that fits in `chunk_max_tokens` becomes exactly one chunk.
   Statute sections are never merged, even when short, so "Section 73"
   always means exactly Section 73.
3. A unit that is too long is split at the best boundary available:
   between blocks first ((1), (2), (a) ...), then between sentences, and
   only as a last resort between words. Each part repeats about
   `chunk_overlap_tokens` of the previous part's last sentences, so it
   still reads sensibly on its own. Parts are labelled "part 2 of 3".
4. Judgment paragraphs shorter than `chunk_min_tokens` are merged with the
   next ones (e.g. "Paras 4-6") up to the size limit.
5. Chapter and heading lines are not chunked on their own; they become
   `heading_path` context (["Chapter VI", ...]) stored with every chunk.

PAGE REFERENCES
Every block remembers its page, so every chunk knows the first and last
page its text came from (page_start / page_end). A section that starts at
the bottom of page 11 and ends on page 12 records 11-12.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.ingestion.chunking.cleaner import CleaningReport, clean_pages
from app.ingestion.chunking.structure import Block, BlockKind, Mode, detect_structure
from app.ingestion.chunking.tokens import METHOD as TOKEN_METHOD
from app.ingestion.chunking.tokens import estimate_tokens
from app.ingestion.extraction_types import ExtractionResult

CHUNKER_VERSION = "1.0"  # stored with each chunk; bump when the rules change


@dataclass
class Chunk:
    chunk_index: int
    text: str
    section_ref: str | None        # "Section 73", "Para 12", "Paras 4-6", "Preamble"
    page_start: int | None
    page_end: int | None
    heading_path: list[str]        # ["Chapter VI"] - where this chunk sits
    unit_kind: str                 # section / numbered_paragraph / heading / preamble
    part: int = 1                  # 2 = second part of a split unit
    parts: int = 1
    overlap_tokens: int = 0        # tokens repeated from the previous part
    token_count: int = 0

    @property
    def char_count(self) -> int:
        return len(self.text)


@dataclass
class ChunkingResult:
    chunks: list[Chunk]
    mode: Mode
    cleaning: CleaningReport
    warnings: list[str] = field(default_factory=list)

    def summary(self) -> dict:
        tokens = [c.token_count for c in self.chunks] or [0]
        return {
            "mode": self.mode.value,
            "chunks": len(self.chunks),
            "chunks_split": sum(1 for c in self.chunks if c.parts > 1),
            "tokens_min": min(tokens),
            "tokens_max": max(tokens),
            "tokens_avg": round(sum(tokens) / len(tokens), 1),
            "token_estimate": TOKEN_METHOD,
            "chunker_version": CHUNKER_VERSION,
            "cleaning": self.cleaning.to_dict(),
            "warnings": sorted(set(self.warnings)),
        }


# ---------------------------------------------------------------------------
# Step 1: units
# ---------------------------------------------------------------------------
@dataclass
class _Unit:
    blocks: list[Block]
    kind: str
    label: str | None
    heading_path: list[str]

    @property
    def text(self) -> str:
        return "\n\n".join(b.text for b in self.blocks)


def _build_units(blocks: list[Block], mode: Mode) -> list[_Unit]:
    units: list[_Unit] = []
    chapter: str | None = None
    heading: str | None = None
    current: _Unit | None = None

    def path() -> list[str]:
        return [p for p in (chapter, heading) if p]

    for block in blocks:
        if block.kind == BlockKind.CHAPTER:
            # A chapter line resets the heading below it and starts context.
            chapter = block.text[:120]
            heading = None
            current = None
            continue
        if block.kind == BlockKind.HEADING:
            heading = block.label
            # The heading text stays in the chunk too (it often carries
            # meaning, e.g. "FACTS" or a section title on its own line).
            current = _Unit([block], "heading", block.label, path())
            units.append(current)
            continue
        if block.kind.starts_unit:  # SECTION or NUMBERED_PARA
            # A heading immediately followed by a section becomes that
            # section's first line rather than a unit of its own.
            if current is not None and current.kind == "heading" and len(current.blocks) == 1:
                units.pop()
                current = _Unit([current.blocks[0], block], block.kind.value, block.label, path())
            else:
                current = _Unit([block], block.kind.value, block.label, path())
            units.append(current)
            continue
        # Sub-sections, clauses, explanations, plain paragraphs: belong to
        # the current unit; text before any unit is the preamble.
        if current is None:
            current = _Unit([], "preamble", "Preamble" if mode == Mode.STATUTE else None, path())
            units.append(current)
        current.blocks.append(block)
    return [u for u in units if u.blocks]


# ---------------------------------------------------------------------------
# Step 3: splitting helpers
# ---------------------------------------------------------------------------
# Common legal abbreviations that end with "." but do not end a sentence.
_ABBREVIATIONS = {
    "rs", "no", "nos", "sec", "secs", "s", "ss", "v", "vs", "art", "arts", "cl", "cls",
    "dr", "mr", "mrs", "ms", "hon", "hon'ble", "j", "jj", "cj", "i.e", "e.g", "etc",
    "viz", "ltd", "pvt", "co", "govt", "dept", "para", "paras", "p", "pp", "vol",
    "ors", "anr", "st", "sub", "ibid", "supra", "u/s", "w.e.f",
}
_SENTENCE_END_RE = re.compile(r"[.?!;](?=[\"')\]]*\s+[\"'(\[]?[A-Z0-9(])")


def split_sentences(text: str) -> list[str]:
    """Split text into sentences without breaking at "Rs." / "No." / "v." etc."""
    sentences, start = [], 0
    for match in _SENTENCE_END_RE.finditer(text):
        end = match.end()
        word = re.findall(r"[\w.'/]+$", text[start:match.start()])
        if text[match.start()] == "." and word and word[-1].lower().rstrip(".") in _ABBREVIATIONS:
            continue
        sentence = text[start:end].strip()
        if sentence:
            sentences.append(sentence)
        start = end
    tail = text[start:].strip()
    if tail:
        sentences.append(tail)
    return sentences


def _split_words(text: str, max_tokens: int) -> list[str]:
    """Last resort for one enormous 'sentence' (e.g. a long table row)."""
    pieces, current = [], []
    for word in text.split():
        if current and estimate_tokens(" ".join(current + [word])) > max_tokens:
            pieces.append(" ".join(current))
            current = []
        current.append(word)
    if current:
        pieces.append(" ".join(current))
    return pieces


@dataclass
class _Piece:
    """A run of text that must not be cut, with the page it came from."""

    text: str
    page_number: int | None
    new_block: bool  # True if it starts a new block (joined with a blank line)


def _pieces_for(unit: _Unit, max_tokens: int) -> list[_Piece]:
    """Break a unit into pieces no bigger than max_tokens, best boundary first."""
    pieces: list[_Piece] = []
    for block in unit.blocks:
        if estimate_tokens(block.text) <= max_tokens:
            pieces.append(_Piece(block.text, block.page_number, True))
            continue
        first = True
        for sentence in split_sentences(block.text):
            parts = [sentence] if estimate_tokens(sentence) <= max_tokens else _split_words(sentence, max_tokens)
            for part in parts:
                pieces.append(_Piece(part, block.page_number, first))
                first = False
    return pieces


def _join(pieces: list[_Piece]) -> str:
    text = ""
    for piece in pieces:
        if not text:
            text = piece.text
        else:
            text += ("\n\n" if piece.new_block else " ") + piece.text
    return text


def _pages(pieces: list[_Piece]) -> tuple[int | None, int | None]:
    numbers = [p.page_number for p in pieces if p.page_number is not None]
    return (min(numbers), max(numbers)) if numbers else (None, None)


def _overlap_from(pieces: list[_Piece], overlap_tokens: int) -> list[_Piece]:
    """Whole sentences from the end of `pieces`, up to `overlap_tokens`."""
    if overlap_tokens <= 0:
        return []
    tail_text = pieces[-1].text
    chosen: list[str] = []
    for sentence in reversed(split_sentences(tail_text)):
        if estimate_tokens(" ".join([sentence] + chosen)) > overlap_tokens:
            break
        chosen.insert(0, sentence)
    if not chosen:
        return []
    return [_Piece(" ".join(chosen), pieces[-1].page_number, True)]


def _split_unit(unit: _Unit, max_tokens: int, overlap_tokens: int) -> list[tuple[list[_Piece], int]]:
    """Greedy packing of pieces into parts; returns (pieces, overlap_tokens_used) per part."""
    parts: list[tuple[list[_Piece], int]] = []
    current: list[_Piece] = []
    current_overlap = 0
    for piece in _pieces_for(unit, max_tokens):
        if current and estimate_tokens(_join(current + [piece])) > max_tokens:
            parts.append((current, current_overlap))
            overlap = _overlap_from(current, overlap_tokens)
            # Only keep the overlap if it still leaves room for new text.
            if overlap and estimate_tokens(_join(overlap + [piece])) <= max_tokens:
                current, current_overlap = overlap, estimate_tokens(overlap[0].text)
            else:
                current, current_overlap = [], 0
        current.append(piece)
    if current:
        parts.append((current, current_overlap))
    return parts


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------
def chunk_document(
    result: ExtractionResult,
    mode: Mode,
    *,
    max_tokens: int = 400,
    overlap_tokens: int = 50,
    min_tokens: int = 40,
    header_footer_min_ratio: float = 0.5,
) -> ChunkingResult:
    """Clean -> detect structure -> build units -> make chunks."""
    cleaned, report = clean_pages(result.pages, header_footer_min_ratio)
    blocks = detect_structure(cleaned, mode)
    units = _build_units(blocks, mode)

    warnings: list[str] = []
    if mode == Mode.STATUTE and not any(u.kind == BlockKind.SECTION.value for u in units):
        warnings.append("no_sections_detected")
    if not result.page_numbers_reliable:
        warnings.append("page_numbers_estimated_or_missing")

    chunks: list[Chunk] = []
    for unit in units:
        parts = _split_unit(unit, max_tokens, overlap_tokens)
        for number, (pieces, overlap_used) in enumerate(parts, start=1):
            page_start, page_end = _pages(pieces)
            text = _join(pieces)
            new_chunk = Chunk(
                chunk_index=0,
                text=text,
                section_ref=unit.label,
                page_start=page_start,
                page_end=page_end,
                heading_path=list(unit.heading_path),
                unit_kind=unit.kind,
                part=number,
                parts=len(parts),
                overlap_tokens=overlap_used,
                token_count=estimate_tokens(text),
            )
            if _should_merge(chunks, new_chunk, mode, min_tokens, max_tokens):
                _merge_into(chunks[-1], new_chunk)
            else:
                chunks.append(new_chunk)

    for index, chunk in enumerate(chunks):
        chunk.chunk_index = index
    return ChunkingResult(chunks, mode, report, warnings)


def _should_merge(chunks: list[Chunk], new: Chunk, mode: Mode, min_tokens: int, max_tokens: int) -> bool:
    """Rule 4: merge short judgment paragraphs; never merge statute sections."""
    if mode != Mode.JUDGMENT or not chunks:
        return False
    last = chunks[-1]
    return (
        last.parts == 1
        and new.parts == 1
        and (last.token_count < min_tokens or new.token_count < min_tokens)
        and last.heading_path == new.heading_path
        and estimate_tokens(last.text + "\n\n" + new.text) <= max_tokens
    )


def _merge_into(last: Chunk, new: Chunk) -> None:
    last.text = last.text + "\n\n" + new.text
    last.token_count = estimate_tokens(last.text)
    last.section_ref = _merge_labels(last.section_ref, new.section_ref)
    starts = [p for p in (last.page_start, new.page_start) if p is not None]
    ends = [p for p in (last.page_end, new.page_end) if p is not None]
    last.page_start = min(starts) if starts else None
    last.page_end = max(ends) if ends else None


def _merge_labels(first: str | None, second: str | None) -> str | None:
    """'Para 4' + 'Para 5' -> 'Paras 4-5'; 'Paras 4-5' + 'Para 6' -> 'Paras 4-6'."""
    numbers = [n for label in (first, second) if label for n in re.findall(r"\d+", label)]
    if numbers and all((label or "").startswith("Para") for label in (first, second) if label):
        return f"Paras {numbers[0]}-{numbers[-1]}" if len(numbers) > 1 else f"Para {numbers[0]}"
    return first or second
