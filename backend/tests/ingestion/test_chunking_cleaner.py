"""
Acceptance criterion: "Extracted text is cleaned and normalized."
"""

from app.ingestion.chunking.cleaner import (
    clean_pages,
    dehyphenate,
    is_page_number_line,
    lines_to_paragraphs,
    normalise_characters,
)

from .helpers import pages_result


def test_characters_are_normalised():
    raw = "Sigﬁed by “the party” and ‘seller’​; soft­hyphen"
    assert normalise_characters(raw) == 'Sigfied by "the party" and \'seller\'; softhyphen'


def test_legal_dashes_are_kept():
    # "commencement.—(1)" style dashes carry meaning and must survive.
    assert normalise_characters("commencement.—(1)") == "commencement.—(1)"


def test_page_number_lines_recognised():
    for line in ["3", "- 3 -", "Page 3", "Page 3 of 42", "[12]", "page 7/40"]:
        assert is_page_number_line(line), line
    for line in ["73. Compensation", "Section 3", "(3) It applies", "2026 judgment"]:
        assert not is_page_number_line(line), line


def test_words_split_at_line_end_are_joined():
    text, fixed = dehyphenate("entitled to compen-\nsation for loss.\nNon-\nResident stays")
    assert "compensation" in text
    assert "Non-\nResident" in text  # next line starts upper-case: keep the hyphen
    assert fixed == 1


def test_lines_rebuilt_into_paragraphs_without_merging_legal_units():
    lines = [
        "73. Compensation for loss or damage caused by breach of contract.-When a contract has been",
        "broken, the party who suffers by such breach is entitled to receive, from the party who has",
        "broken the contract, compensation.",
        "(1) The first sub-section starts on its own line and continues on the",
        "next line as part of the same sub-section.",
        "(a) a clause",
        "Explanation.-An explanation is its own paragraph.",
    ]
    paragraphs = lines_to_paragraphs(lines)
    assert len(paragraphs) == 4
    assert paragraphs[0].startswith("73. Compensation") and paragraphs[0].endswith("compensation.")
    assert "has been broken, the party" in paragraphs[0]  # wrapped line joined with a space
    assert paragraphs[1].startswith("(1)") and paragraphs[1].endswith("same sub-section.")
    assert paragraphs[2] == "(a) a clause"
    assert paragraphs[3].startswith("Explanation")


def test_running_headers_and_page_numbers_removed_but_page_numbers_kept():
    pages = [
        f"THE GAZETTE OF INDIA {n}\nSection {n}. Some real text on page {n} of the Act.\n- {n} -"
        for n in range(1, 5)
    ]
    cleaned, report = clean_pages(pages_result(pages).pages)
    for number, page in enumerate(cleaned, start=1):
        assert page.page_number == number  # page reference preserved
        assert "GAZETTE" not in page.text
        assert f"- {number} -" not in page.text
        assert f"page {number} of the Act" in page.text
    assert report.header_footer_patterns >= 1
    assert report.edge_lines_removed == 8


def test_headers_not_guessed_from_two_pages():
    # With fewer than 3 pages a repeated line could be real text: keep it.
    cleaned, _ = clean_pages(pages_result(["Same first line\nbody one", "Same first line\nbody two"]).pages)
    assert all("Same first line" in page.text for page in cleaned)
