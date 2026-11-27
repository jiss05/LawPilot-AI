"""
Neutrality guard for the Judge Support Agent (SCRUM-25: "Summaries remain
neutral" and "The agent does not make judicial decisions or recommend case
outcomes").

The model is told to stay neutral, but a prompt is not a guarantee. Every
judge-support output passes through `enforce_neutrality`, which removes any
sentence that decides the case, predicts its outcome or recommends what the
court should do, and says that it did so. Neutral phrasings such as "the
court must decide whether ..." are kept.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_PARTY = r"(?:petitioner|respondent|plaintiff|defendant|appellant|accused|prosecution|complainant|applicant|claimant|state)s?"

_DECISION_PATTERNS = [
    # Recommending an outcome
    r"\b(?:i|we)\s+(?:would\s+)?(?:recommend|advise|suggest|urge|propose)\b",
    r"\b(?:it\s+is\s+)?(?:recommended|advisable)\s+that\s+the\s+(?:court|judge|bench|tribunal)\b",
    r"\bthe\s+(?:court|judge|bench|tribunal|your\s+honou?r)\s+(?:should|must|ought\s+to|needs\s+to|has\s+to)\s+"
    r"(?!(?:consider|determine|decide\s+whether|decide\s+if|examine|assess|evaluate|weigh|review|address|note)\b)",
    # Disposing of the case
    r"\b(?:should|must|ought\s+to)\s+be\s+(?:dismissed|allowed|granted|rejected|refused|acquitted|convicted|"
    r"quashed|upheld|set\s+aside|decreed|struck\s+out|sentenced)\b",
    r"\b(?:petition|appeal|suit|application|case|claim|complaint|bail)\s+(?:is|will\s+be|would\s+be)\s+"
    r"(?:dismissed|allowed|granted|rejected|refused|quashed|upheld|decreed)\b",
    # Findings of guilt or liability
    r"\b(?:is|are|was|were)\s+(?:clearly\s+|therefore\s+)?(?:guilty|not\s+guilty|innocent|liable|not\s+liable)\b",
    # Choosing a side / predicting outcome
    rf"\b(?:decide|rule|find|hold|judgment)\s+(?:in\s+favou?r\s+of|for|against)\s+the\s+{_PARTY}\b",
    rf"\bthe\s+{_PARTY}\s+(?:should|will|would|is\s+likely\s+to|are\s+likely\s+to)\s+(?:win|succeed|prevail|lose|fail)\b",
    rf"\b{_PARTY}\s+(?:has|have)\s+(?:the\s+)?(?:stronger|better|weaker)\s+(?:case|argument|position)\b",
    rf"\b(?:stronger|weaker|better|more\s+persuasive|less\s+persuasive)\s+(?:case|argument|position)\s+(?:is|lies)\s+with\b",
    r"\b(?:likely|probable|expected)\s+(?:outcome|result|verdict|decision)\b",
    r"\b(?:verdict|judgment|order|decision)\s+should\b",
]
_DECISION_RE = [re.compile(p, re.IGNORECASE) for p in _DECISION_PATTERNS]
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

NEUTRALITY_NOTE = (
    "Note: {n} statement(s) that suggested a decision or outcome were removed. "
    "LawPilot does not decide cases or recommend outcomes; the decision rests "
    "with the court."
)


@dataclass
class NeutralityResult:
    text: str
    removed: list[str] = field(default_factory=list)

    @property
    def neutral(self) -> bool:
        return not self.removed


# "Whether the accused is liable ..." frames an issue for the court; it does
# not decide it.
_QUESTION_FRAME_RE = re.compile(r"\b(?:whether|if)\b|\?", re.IGNORECASE)


def is_decisional(sentence: str) -> bool:
    for pattern in _DECISION_RE:
        match = pattern.search(sentence)
        if match and not _QUESTION_FRAME_RE.search(sentence[: match.start()]) and not sentence.rstrip().endswith("?"):
            return True
    return False


def enforce_neutrality(text: str, *, add_note: bool = True) -> NeutralityResult:
    """Remove decisional sentences from `text`, keeping its line structure."""
    if not text:
        return NeutralityResult(text or "")
    removed: list[str] = []
    out_lines: list[str] = []
    for line in text.split("\n"):
        kept = []
        for sentence in re.split(r"(?<=[.!?])\s+", line):
            if sentence.strip() and is_decisional(sentence):
                removed.append(sentence.strip())
            else:
                kept.append(sentence)
        joined = " ".join(s for s in kept if s is not None).rstrip()
        # Drop a list item / line that became empty apart from its bullet.
        if line.strip() and not re.sub(r"^[\s\-*•\d.)]+", "", joined):
            continue
        out_lines.append(joined)
    cleaned = "\n".join(out_lines).strip()
    if removed and add_note:
        cleaned = (cleaned + "\n\n" if cleaned else "") + NEUTRALITY_NOTE.format(n=len(removed))
    return NeutralityResult(cleaned, removed)
