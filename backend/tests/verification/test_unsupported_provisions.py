"""SCRUM-26: law named in an answer must exist in the retrieved sources."""

import pytest

from app.safety.responses import assess_reliability
from app.verification.citations import stored_sources_from_retrieved, verify_citations
from app.verification.provisions import acts_named, provisions_named, unsupported_mentions

# What retrieval returned for "Can I be released on bail if I am arrested for theft?"
# (the Contract Act's chapter on BAILMENT - same word, different subject).
BAILMENT = [
    {"chunk_id": f"c{i}", "source_title": "indian-contract-act", "section_ref": f"Section {s}",
     "citation": f"Section {s}, p. {p}",
     "text": f"{s}. {body}"}
    for i, (s, p, body) in enumerate([
        (160, 40, "Return of goods bailed, on expiration of time or accomplishment of purpose."),
        (154, 39, "Bailor's responsibility to bailee for expenses."),
        (167, 41, "Right of third person claiming goods bailed. If a person, other than the bailor, "
                  "claims goods bailed, he may apply to the Court to stop the delivery of the goods to the bailor."),
        (165, 41, "Bailment by several joint owners."),
        (171, 42, "General lien of bankers, factors, wharfingers, attorneys and policy-brokers."),
    ], 1)
]

HALLUCINATED = (
    "The legal framework for releasing someone on bail after an arrest for theft is primarily governed by "
    "the **Code of Criminal Procedure, 1974 (CrPC)**, specifically Sections 462 and 463.\n"
    "1. **Section 462 of the CrPC**: This section allows the court to grant bail [3].\n"
    "2. **Section 463 of the CrPC**: The court may also grant bail [3]."
)


def citations():
    return [{"ref": i, "chunk_id": s["chunk_id"], "source_title": s["source_title"], "citation": s["citation"]}
            for i, s in enumerate(BAILMENT, 1)]


def test_the_reported_answer_is_flagged():
    missing = unsupported_mentions(HALLUCINATED, BAILMENT)
    assert "Section 462" in missing and "Section 463" in missing
    assert any(m.startswith("Code of Criminal Procedure") for m in missing)

    report = verify_citations(HALLUCINATED, citations(), stored_sources_from_retrieved(BAILMENT))
    assert report.has_failures and not report.verified
    r = assess_reliability(status="completed", citations=citations(), verification=report, conflicts=[])
    assert r.reliable is False
    assert "Section 462" in r.notice and "not in the retrieved sources" in r.notice


def test_correct_answer_still_passes():
    answer = "Under Section 167 of the Indian Contract Act, a third person claiming goods bailed may apply to the Court [3]."
    report = verify_citations(answer, citations(), stored_sources_from_retrieved(BAILMENT))
    assert report.unsupported_mentions == []
    assert report.verified


@pytest.mark.parametrize("answer, source", [
    ("Article 21 of the Constitution of India protects life and personal liberty [1].",
     {"source_title": "Constitution of India", "text": "21. Protection of life and personal liberty.— No person shall..."}),
    ("Under s. 138 of the Negotiable Instruments Act, 1881 dishonour is an offence [1].",
     {"source_title": "Negotiable Instruments Act, 1881", "section_ref": "Section 138", "text": "Dishonour of cheque..."}),
    ("Theft is defined in Section 303 of the Bharatiya Nyaya Sanhita, 2023 [1].",
     {"source_title": "Bharatiya Nyaya Sanhita, 2023", "text": "303. (1) Whoever, intending to take dishonestly..."}),
    ("Articles 14 and 21 apply [1].",
     {"source_title": "Constitution of India", "text": "Article 14. Equality before law. ... Article 21. Protection of life"}),
])
def test_supported_provisions_pass(answer, source):
    assert unsupported_mentions(answer, [source]) == []


@pytest.mark.parametrize("answer, expected", [
    ("Article 21 of the Constitution of India applies [1].", "Article 21"),
    ("See Section 420 of the Indian Penal Code [1].", "Section 420"),
    ("The Indian Penal Code, 1860 applies [1].", "Indian Penal Code, 1860"),
    ("Under the Indian Contract Act, 1950 [1].", "Indian Contract Act, 1950"),   # wrong year
])
def test_unsupported_provisions_fail(answer, expected):
    source = {"source_title": "Indian Contract Act, 1872", "section_ref": "Section 73",
              "text": "73. Compensation for loss or damage caused by breach of contract."}
    assert expected in unsupported_mentions(answer, [source])


def test_parsing():
    assert provisions_named("Sections 462 and 463; Articles 14, 19 & 21; s. 138A") == [
        ("section", "462"), ("section", "463"), ("article", "14"), ("article", "19"),
        ("article", "21"), ("section", "138A")]
    assert acts_named("under the Code of Criminal Procedure, 1973 and the Act") == ["Code of Criminal Procedure, 1973"]
    assert acts_named("This Act and the Code apply.") == []
