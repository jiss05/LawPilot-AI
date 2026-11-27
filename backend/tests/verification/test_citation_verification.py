"""SCRUM-26: citation verification against stored legal sources."""

from app.verification.citations import (
    ISSUE_INVALID_REFERENCE,
    ISSUE_MISSING_LOCATOR,
    ISSUE_QUOTE_MISMATCH,
    ISSUE_SOURCE_INACTIVE,
    ISSUE_SOURCE_MISMATCH,
    ISSUE_SOURCE_NOT_FOUND,
    STATUS_FAILED,
    STATUS_NOT_CITED,
    STATUS_VERIFIED,
    referenced_numbers,
    stored_sources_from_retrieved,
    verify_citations,
)

STORED = {
    "c1": {
        "text": "Section 73. When a contract has been broken, the party who suffers by such "
                "breach is entitled to receive compensation for any loss or damage caused to him.",
        "source_title": "Indian Contract Act, 1872",
        "citation": "Section 73, p. 21",
        "section_ref": "Section 73",
        "page_number": 21,
        "active": True,
    },
    "c2": {
        "text": "Every person shall be liable to punishment under this Code.",
        "source_title": "Bharatiya Nyaya Sanhita, 2023",
        "citation": None,
        "section_ref": None,
        "page_number": None,
        "active": True,
    },
}

C1 = {"ref": 1, "chunk_id": "c1", "source_title": "Indian Contract Act, 1872", "citation": "Section 73, p. 21"}
C2 = {"ref": 2, "chunk_id": "c2", "source_title": "Bharatiya Nyaya Sanhita, 2023"}


def test_supported_citation_is_verified():
    report = verify_citations("Compensation is available for breach [1].", [C1], STORED)
    assert report.checks[0].status == STATUS_VERIFIED
    assert report.verified is True
    assert report.has_failures is False


def test_citation_to_unknown_stored_source_is_flagged():
    fake = {"ref": 1, "chunk_id": "does-not-exist", "source_title": "Made Up Act"}
    report = verify_citations("The Made Up Act says so [1].", [fake], STORED)
    check = report.checks[0]
    assert check.status == STATUS_FAILED
    assert ISSUE_SOURCE_NOT_FOUND in check.issues
    assert report.verified is False


def test_reference_number_without_a_source_is_flagged():
    report = verify_citations("Supported [1] but also see [7].", [C1], STORED)
    assert report.invalid_refs == [7]
    assert report.verified is False
    # the valid one is still verified individually
    assert report.checks[0].status == STATUS_VERIFIED


def test_title_mismatch_is_flagged():
    wrong = {**C1, "source_title": "Specific Relief Act"}
    report = verify_citations("Damages follow breach [1].", [wrong], STORED)
    assert ISSUE_SOURCE_MISMATCH in report.checks[0].issues


def test_missing_locator_is_identified():
    report = verify_citations("Everyone is liable [2].", [C2], STORED)
    check = report.checks[0]
    assert check.status == STATUS_FAILED
    assert ISSUE_MISSING_LOCATOR in check.issues
    assert any("locator" in d for d in check.details)


def test_inactive_edition_is_flagged():
    stored = {"c1": {**STORED["c1"], "active": False}}
    report = verify_citations("Compensation [1].", [C1], stored)
    assert ISSUE_SOURCE_INACTIVE in report.checks[0].issues


def test_exact_quote_passes_and_misquote_fails():
    good = 'The Act says the party "is entitled to receive compensation for any loss" [1].'
    assert verify_citations(good, [C1], STORED).checks[0].status == STATUS_VERIFIED

    bad = 'The Act says the party "is entitled to punitive damages of any amount" [1].'
    check = verify_citations(bad, [C1], STORED).checks[0]
    assert check.status == STATUS_FAILED
    assert ISSUE_QUOTE_MISMATCH in check.issues
    assert any("punitive damages" in d for d in check.details)


def test_quote_matching_ignores_case_and_punctuation():
    text = "It provides that “the party who suffers by such breach is entitled” [1]."
    assert verify_citations(text, [C1], STORED).checks[0].status == STATUS_VERIFIED


def test_unattributed_invented_quote_fails_report():
    text = 'Compensation is due [1]. As held, "courts must always award double damages".'
    report = verify_citations(text, [C1], STORED)
    assert report.unattributed_quotes
    assert report.verified is False


def test_uncited_source_is_not_shown_as_verified():
    report = verify_citations("Compensation is due [1].", [C1, C2], STORED)
    assert report.checks[1].status == STATUS_NOT_CITED
    assert report.verified is True  # nothing that was relied on failed


def test_answer_without_any_reference_is_not_verified():
    report = verify_citations("Compensation is due.", [C1], STORED)
    assert report.checks[0].status == STATUS_NOT_CITED
    assert report.verified is False


def test_annotate_adds_fields_in_order():
    report = verify_citations("Due [1]. Liable [2].", [C1, C2], STORED)
    out = report.annotate([C1, C2])
    assert [c["verification_status"] for c in out] == [STATUS_VERIFIED, STATUS_FAILED]
    assert out[0]["source_title"] == C1["source_title"]


def test_reference_parsing():
    assert referenced_numbers("a [1] b [2, 3] c [1][4]") == [1, 2, 3, 4]


def test_stored_sources_from_retrieved():
    stored = stored_sources_from_retrieved([{"chunk_id": "x", "text": "t", "source_title": "T",
                                             "section_ref": "Section 1"}])
    assert stored["x"]["section_ref"] == "Section 1"
    assert stored["x"]["active"] is True
