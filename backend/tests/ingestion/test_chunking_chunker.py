"""
Acceptance criteria:
  * "Documents are divided into meaningful chunks."
  * "Each chunk maintains its source and page references."
  * "Legal sections and paragraphs are preserved."
"""

import re

import pytest

from app.ingestion.chunking import chunk_document
from app.ingestion.chunking.chunker import split_sentences
from app.ingestion.chunking.structure import Mode
from app.ingestion.chunking.tokens import estimate_tokens
from app.ingestion.extractor import DocumentExtractor

from .helpers import make_docx, make_statute_pdf, pages_result


@pytest.fixture
def statute_chunks(settings, tmp_path):
    no_ocr = settings.model_copy(update={"ocr_enabled": False})
    result = DocumentExtractor(no_ocr).extract(make_statute_pdf(tmp_path / "act.pdf"))
    return chunk_document(result, Mode.STATUTE)


def test_one_chunk_per_section_with_chapter_context(statute_chunks):
    refs = [c.section_ref for c in statute_chunks.chunks]
    assert refs[:2] == ["Section 1", "Section 2"]
    assert refs[-1] == "Section 74"
    first = statute_chunks.chunks[0]
    assert first.heading_path == ["CHAPTER I", "PRELIMINARY"]
    # Sub-sections and clauses stay inside their section.
    assert "(2) It extends to the whole of India." in first.text
    assert "(a) when one person" in statute_chunks.chunks[1].text


def test_long_section_split_into_labelled_parts_with_overlap(statute_chunks):
    s73 = [c for c in statute_chunks.chunks if c.section_ref == "Section 73"]
    assert len(s73) >= 2
    assert [c.part for c in s73] == list(range(1, len(s73) + 1))
    assert all(c.parts == len(s73) for c in s73)
    assert all(c.token_count <= 400 for c in s73)
    # parts after the first repeat the end of the previous part
    for previous, current in zip(s73, s73[1:]):
        assert current.overlap_tokens > 0
        last_sentence = split_sentences(previous.text)[-1]
        assert current.text.startswith(last_sentence)
    # Nothing lost: every numbered sentence appears in some part.
    found = {int(n) for c in s73 for n in re.findall(r"Sentence (\d+) ", c.text)}
    assert found == set(range(1, 40))
    # The Explanation belongs to Section 73, not to Section 74.
    assert "Explanation" in s73[-1].text


def test_page_references_follow_the_text(statute_chunks):
    by_ref = {}
    for c in statute_chunks.chunks:
        by_ref.setdefault(c.section_ref, []).append(c)
    assert by_ref["Section 1"][0].page_start == 1 == by_ref["Section 1"][0].page_end
    s73 = by_ref["Section 73"]
    assert s73[0].page_start == 2                      # Section 73 starts on page 2
    assert s73[-1].page_end == 3                       # ... and ends on page 3
    assert by_ref["Section 74"][0].page_start == 3


def test_headers_and_page_numbers_do_not_leak_into_chunks(statute_chunks):
    all_text = "\n".join(c.text for c in statute_chunks.chunks)
    assert "THE SAMPLE CONTRACT ACT, 1872" not in all_text
    assert not re.search(r"^- \d -$", all_text, re.MULTILINE)


def test_chunk_indexes_are_sequential(statute_chunks):
    assert [c.chunk_index for c in statute_chunks.chunks] == list(range(len(statute_chunks.chunks)))


def test_short_statute_sections_are_never_merged():
    result = pages_result(["1. Short title. This Act is the Tiny Act.\n2. Extent. It applies everywhere."])
    chunks = chunk_document(result, Mode.STATUTE).chunks
    assert [c.section_ref for c in chunks] == ["Section 1", "Section 2"]


def test_short_judgment_paragraphs_are_merged():
    page = "JUDGMENT\n1. Heard.\n2. Perused the record.\n3. " + "The appellant contends at length that the contract was broken. " * 30
    chunks = chunk_document(pages_result([page]), Mode.JUDGMENT, min_tokens=40).chunks
    refs = [c.section_ref for c in chunks]
    assert refs[0] == "Paras 1-2"  # two tiny paragraphs combined (the heading merges into para 1)
    assert set(refs[1:]) == {"Para 3"}  # the long paragraph is split, never merged


def test_huge_sentence_is_split_by_words_as_last_resort():
    result = pages_result(["1. Table. " + "word " * 2000])
    chunks = chunk_document(result, Mode.STATUTE, max_tokens=200).chunks
    assert len(chunks) > 1 and all(c.token_count <= 200 for c in chunks)


def test_docx_without_page_info_has_no_page_numbers(settings, tmp_path):
    path = make_docx(tmp_path / "note.docx", pages=[["1. First point. It is short.", "2. Second point. Also short."]])
    result = DocumentExtractor(settings).extract(path)
    chunked = chunk_document(result, Mode.STATUTE)
    assert all(c.page_start is None and c.page_end is None for c in chunked.chunks)
    assert "page_numbers_estimated_or_missing" in chunked.warnings


def test_sentence_splitter_respects_legal_abbreviations():
    text = "The fee is Rs. 500 under Sec. 4 of the Act. See Ram v. Shyam, AIR 1950 SC 1. Then (1) applies."
    assert split_sentences(text) == [
        "The fee is Rs. 500 under Sec. 4 of the Act.",
        "See Ram v. Shyam, AIR 1950 SC 1.",
        "Then (1) applies.",
    ]


def test_token_estimate():
    assert estimate_tokens("") == 0
    assert estimate_tokens("abcd" * 100) == 100
