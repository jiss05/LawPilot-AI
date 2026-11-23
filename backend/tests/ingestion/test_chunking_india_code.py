"""
Tests for the rules added after trying a real India Code PDF
(The Indian Contract Act, 1872). Each test uses a tiny made-up page that
reproduces one problem we saw in the real document.
"""
from app.ingestion.chunking import chunk_document
from app.ingestion.chunking.cleaner import (
    clean_pages,
    find_table_of_contents_pages,
    remove_watermarks,
    split_footnotes,
    split_glued_sections,
)
from app.ingestion.chunking.chunker import CHUNKER_VERSION
from app.ingestion.chunking.structure import BlockKind, Mode, classify, detect_structure
from app.ingestion.extraction_types import ExtractionResult, FileType, PageText


def _page(number: int, text: str) -> PageText:
    return PageText(page_number=number, text=text, method="native")


def _result(*texts: str) -> ExtractionResult:
    pages = [_page(i + 1, t) for i, t in enumerate(texts)]
    return ExtractionResult(file_type=FileType.PDF, pages=pages)


# --- table of contents --------------------------------------------------------

def test_table_of_contents_pages_are_found_until_the_act_begins():
    pages = [
        "THE INDIAN CONTRACT ACT, 1872\nARRANGEMENT OF SECTIONS\n1. Short title.\n2. Interpretation-clause.",
        "3. Communication.\n4. Communication when complete.",
        "THE INDIAN CONTRACT ACT, 1872\nACT NO. 9 OF 1872\n1. Short title.—This Act may be called ...",
        "2. Interpretation-clause.—In this Act ...",
    ]
    assert find_table_of_contents_pages(pages) == {0, 1}


def test_document_without_table_of_contents_keeps_every_page():
    assert find_table_of_contents_pages(["1. Short title.—This Act ...", "2. Definitions.—In this Act ..."]) == set()


# --- footnotes ----------------------------------------------------------------

def test_amendment_footnotes_are_separated_from_the_body():
    lines = [
        "19A. Power to set aside contract induced by undue influence.—When consent",
        "to an agreement is caused by undue influence, the agreement is voidable.",
        "Any such contract may be set aside.",
        "1. The words \"undue influence\" rep. by Act 6 of 1899, s. 3.",
        "2. Ins. by Act 6 of 1899, s. 3.",
    ]
    body, notes = split_footnotes(lines)
    assert body == lines[:3]
    assert notes == lines[3:]


def test_editorial_cross_reference_footnotes_are_separated():
    lines = ["45. Devolution of joint rights.—When a promise ...", "text", "text", "1. See s. 138, infra."]
    body, notes = split_footnotes(lines)
    assert notes == ["1. See s. 138, infra."]


def test_repealed_section_is_not_mistaken_for_a_footnote():
    # "239. ... Rep. by s. 73" uses footnote words but numbering starts at 239.
    lines = [
        "238. Effect of misrepresentation.—Misrepresentation made ...",
        "more text",
        "239. ['Partnership' defined.] Rep. by s. 73 and the Second Schedule, ibid.",
        "240. [Lender not a partner.] Rep. by s. 73 and the Second Schedule, ibid.",
    ]
    body, notes = split_footnotes(lines)
    assert notes == []


# --- watermark and glued sections ----------------------------------------------

def test_india_code_watermark_is_removed():
    assert "IndiaCode" not in remove_watermarks("As betweenIndiaCodethe principal")


def test_section_starting_mid_line_is_moved_to_its_own_line():
    out = split_glued_sections([remove_watermarks("may employ an agent.    184. Who may be an agent.—As between")])
    assert out == ["may employ an agent.", "184. Who may be an agent.—As between"]


# --- section headings ---------------------------------------------------------

def test_section_number_without_space_is_recognised():
    assert classify("73.Compensation for loss or damage caused by breach of contract.—When", Mode.STATUTE) == (
        BlockKind.SECTION, "Section 73")


def test_section_inserted_by_amendment_is_recognised():
    assert classify("2[19A. Power to set aside contract induced by undue influence.—When", Mode.STATUTE) == (
        BlockKind.SECTION, "Section 19A")


def test_sentence_mentioning_a_section_is_not_a_heading():
    kind, _ = classify("Section 294A of the Indian Penal Code not affected.—Nothing in this section", Mode.STATUTE)
    assert kind != BlockKind.SECTION


def test_section_numbers_must_not_go_backwards():
    cleaned, _ = clean_pages([
        _page(1, "10. What agreements are contracts.—All agreements are contracts ..."),
        _page(2, "3. A stray numbered line that is not a section.\n\n11. Who are competent to contract.—Every person"),
    ])
    sections = [b.label for b in detect_structure(cleaned, Mode.STATUTE) if b.kind == BlockKind.SECTION]
    assert sections == ["Section 10", "Section 11"]


def test_footnote_marker_glued_to_section_number_is_repaired():
    cleaned, _ = clean_pages([
        _page(1, "150. Bailor's duty to disclose faults.—The bailor is bound ..."),
        _page(2, "1151. Care to be taken by bailee.—In all cases of bailment ..."),
    ])
    sections = [b.label for b in detect_structure(cleaned, Mode.STATUTE) if b.kind == BlockKind.SECTION]
    assert sections == ["Section 150", "Section 151"]


# --- whole chunker ----------------------------------------------------------------

def test_chunks_carry_page_footnotes_and_drop_fragments():
    result = _result(
        "1. Short title.—This Act may be called the Indian Contract Act, 1872.\n\nIndia\n\n"
        "text\ntext\n1. Subs. by Act 3 of 1951, s. 3 and Sch., for \"Part A States\".",
    )
    chunking = chunk_document(result, Mode.STATUTE)
    assert [c.section_ref for c in chunking.chunks] == ["Section 1"]
    assert chunking.footnotes_for(chunking.chunks[0]) == ['1. Subs. by Act 3 of 1951, s. 3 and Sch., for "Part A States".']
    assert chunking.summary()["chunker_version"] == CHUNKER_VERSION == "1.1"
