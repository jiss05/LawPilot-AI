"""
Acceptance criterion: "Legal sections and paragraphs are preserved."
These tests check that each kind of legal unit is recognised.
"""

import pytest

from app.ingestion.chunking.structure import BlockKind, Mode, classify, mode_for_source_type


@pytest.mark.parametrize(
    "text, kind, label",
    [
        ("CHAPTER VI OF THE CONSEQUENCES OF BREACH", BlockKind.CHAPTER, "Chapter VI"),
        ("PART II", BlockKind.CHAPTER, "Part II"),
        ("THE FIRST SCHEDULE", BlockKind.CHAPTER, "Schedule"),
        ("73. Compensation for loss or damage", BlockKind.SECTION, "Section 73"),
        ("2A. Definitions", BlockKind.SECTION, "Section 2A"),
        ("Section 10. What agreements are contracts", BlockKind.SECTION, "Section 10"),
        ("(1) This Act may be called", BlockKind.SUBSECTION, "(1)"),
        ("(a) when one person signifies", BlockKind.CLAUSE, "(a)"),
        ("(iv) the fourth item", BlockKind.CLAUSE, "(iv)"),
        ("Explanation.-In estimating the loss", BlockKind.EXPLANATION, None),
        ("Illustrations", BlockKind.EXPLANATION, None),
        ("Provided that nothing in this section", BlockKind.EXPLANATION, None),
        ("PRELIMINARY", BlockKind.HEADING, "PRELIMINARY"),
        ("Part of the land was sold to the buyer.", BlockKind.PARAGRAPH, None),
        ("The seller then refused to deliver.", BlockKind.PARAGRAPH, None),
    ],
)
def test_statute_units(text, kind, label):
    assert classify(text, Mode.STATUTE) == (kind, label)


def test_same_numbering_means_paragraph_in_a_judgment():
    assert classify("12. The appellant contends that", Mode.JUDGMENT) == (BlockKind.NUMBERED_PARA, "Para 12")
    assert classify("12. The appellant contends that", Mode.STATUTE)[0] == BlockKind.SECTION


@pytest.mark.parametrize(
    "source_type, mode",
    [("statute", Mode.STATUTE), ("Act", Mode.STATUTE), ("rules", Mode.STATUTE), (None, Mode.STATUTE),
     ("judgment", Mode.JUDGMENT), ("Supreme Court Judgement", Mode.JUDGMENT), ("case_law", Mode.JUDGMENT)],
)
def test_mode_from_source_type(source_type, mode):
    assert mode_for_source_type(source_type) == mode
