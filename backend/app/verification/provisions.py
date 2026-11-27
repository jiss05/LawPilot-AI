"""
Unsupported legal provisions (SCRUM-26: "Invalid source references are flagged").

A citation can point at a real source while the sentence around it names a
provision that source never mentions, e.g. "Sections 462 and 463 of the
CrPC [3]" where [3] is Section 167 of the Contract Act. This module finds
every statute section, article, rule or order, and every Act or Code the
answer NAMES, and checks that the retrieved sources contain it. Anything
named but not found is reported; the answer is then not shown as reliable.

It is deliberately lenient about formatting ("Section 73", "s. 73",
"73." at the start of a statute paragraph all count) and strict about
existence: a provision is supported only if some source mentions it.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, Mapping

from app.verification.citations import normalise

_KIND = {
    "section": "section", "sections": "section", "sec": "section", "secs": "section", "s": "section", "ss": "section",
    "article": "article", "articles": "article", "art": "article", "arts": "article",
    "rule": "rule", "rules": "rule", "order": "order",
}
# "Section 73", "Sections 462 and 463", "Articles 14, 19 and 21", "s. 138", "Art. 21A"
_PROVISION_RE = re.compile(
    r"\b(Sections?|Secs?\.|S{1,2}\.|Articles?|Arts?\.|Rules?|Order)\s*"
    r"(\d{1,4}[A-Z]?)((?:\s*(?:,|and|&|or|to|-)\s*\d{1,4}[A-Z]?)*)",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\d{1,4}[A-Z]?", re.IGNORECASE)
_LOWER_WORDS = {"of", "the", "and", "for", "on", "in"}
# "Code of Criminal Procedure, 1974", "Indian Contract Act", "Bharatiya Nyaya Sanhita, 2023"
_ACT_RE = re.compile(
    r"\b((?:[A-Z][A-Za-z]+\s+)(?:(?:[A-Z][A-Za-z]+|of|the|and|for|on|in)\s+)*?"
    r"(?:Act|Code|Sanhita|Adhiniyam|Constitution))\b(?:,?\s*(\d{4}))?"
)
# "Code of Criminal Procedure, 1973", "Constitution of India", "Code of Civil Procedure"
_CODE_OF_RE = re.compile(
    r"\b((?:Code|Constitution)\s+of\s+[A-Z][A-Za-z]+(?:\s+[A-Z][A-Za-z]+)*)\b(?:,?\s*(\d{4}))?"
)
_GENERIC_ACTS = {"the act", "this act", "the code", "this code", "the constitution", "this constitution"}
_TERMINATORS = {"Act", "Code", "Sanhita", "Adhiniyam", "Constitution", "India", "Procedure"}


def _source_blob(src: Mapping[str, Any]) -> str:
    return "\n".join(str(src.get(k) or "") for k in ("source_title", "citation", "section_ref", "text"))


def _provision_supported(kind: str, number: str, blobs: list[str]) -> bool:
    n = re.escape(number)
    patterns = [
        rf"\b{kind}s?\s*{n}\b",
        rf"\b{kind[:3]}s?\.?\s*{n}\b",
        rf"(?:^|\n)\s*{n}\s*[.)\-]\s",       # statute paragraph heading "73. When a contract..."
    ]
    if kind == "section":
        patterns.append(rf"\bs{{1,2}}\.\s*{n}\b")
    if kind == "article":
        patterns.append(rf"\bart\.\s*{n}\b")
    return any(re.search(p, blob, re.IGNORECASE) for p in patterns for blob in blobs)


def provisions_named(text: str) -> list[tuple[str, str]]:
    """(kind, number) for every provision named in the text, in order, without repeats."""
    found: list[tuple[str, str]] = []
    for match in _PROVISION_RE.finditer(text or ""):
        kind = _KIND.get(match.group(1).lower().rstrip("."), "section")
        numbers = [match.group(2)] + _NUMBER_RE.findall(match.group(3) or "")
        for number in numbers:
            item = (kind, number.upper())
            if item not in found:
                found.append(item)
    return found


def acts_named(text: str) -> list[str]:
    """Names of Acts/Codes mentioned in the text (as written)."""
    names: list[str] = []
    matches = sorted(
        list(_ACT_RE.finditer(text or "")) + list(_CODE_OF_RE.finditer(text or "")),
        key=lambda m: m.start(),
    )
    for match in matches:
        name = match.group(1).strip()
        words = name.split()
        while words and words[0].lower() in _LOWER_WORDS | {"under", "per", "by", "see"}:
            words.pop(0)
        # "Constitution of India and Indian Contract Act": two names joined by
        # "and"; keep only the last one here (the first is matched separately).
        for i in range(len(words) - 2, 0, -1):
            if words[i].lower() == "and" and words[i - 1].rstrip(",") in _TERMINATORS:
                words = words[i + 1:]
                break
        name = " ".join(words)
        if len(words) < 2 or normalise(name) in _GENERIC_ACTS:
            continue
        full = f"{name}, {match.group(2)}" if match.group(2) else name
        if full not in names:
            names.append(full)
    return names


def _act_supported(name: str, blobs_norm: list[str]) -> bool:
    title, _, year = name.partition(", ")
    key_words = [w for w in normalise(title).split() if w not in _LOWER_WORDS]
    if not key_words:
        return True
    for blob in blobs_norm:
        if all(w in blob for w in key_words) and (not year or year in blob):
            return True
    return False


def unsupported_mentions(text: str, sources: Iterable[Mapping[str, Any]]) -> list[str]:
    """Provisions and Acts named in `text` that no source mentions, e.g. ["Section 462", "Code of Criminal Procedure, 1974"]."""
    blobs = [_source_blob(s) for s in sources or []]
    blobs_norm = [normalise(b) for b in blobs]
    missing: list[str] = []
    for kind, number in provisions_named(text):
        if not _provision_supported(kind, number, blobs):
            missing.append(f"{kind.capitalize()} {number}")
    for act in acts_named(text):
        if not _act_supported(act, blobs_norm):
            missing.append(act)
    return missing
