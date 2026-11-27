"""
Structured case brief for the Judge Support Agent (SCRUM-25).

    facts (each with a source_ref) ─┐
    parties and their arguments ────┼─► build_case_brief() ─► CaseBrief
    retrieved legal sources ────────┘

Acceptance criteria:
  * Only authorized users can access the workspace -> the API checks the
    judge_support agent permission (JUDGE, ADMIN) before calling this.
  * Case facts retain source references -> every fact needs a source_ref,
    keeps it in facts/chronology/issues; model output may only point at
    fact ids that exist (unknown ids are dropped).
  * Chronology and disputed issues are generated -> chronology is built
    deterministically from the fact dates; issues come from facts marked
    disputed plus model-identified issues (validated).
  * Both parties' arguments are organized separately -> party_arguments is
    built per party from the input, never merged or rewritten by the model.
  * Summaries remain neutral / no decisions or recommendations -> the
    summary and every model issue pass enforce_neutrality(); decisional
    issues are dropped.

If the model is unavailable the brief is still returned (facts, chronology,
flagged issues and arguments are deterministic) with a plain warning.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Callable

from app.agents.base import JUDGE_SUPPORT_AGENT
from app.agents.default_agents import JudgeSupportAgent, citations_for, format_sources
from app.agents.neutrality import enforce_neutrality, is_decisional
from app.llm.gateway import ModelGateway
from app.llm.types import ChatMessage, GenerationRequest, ModelError
from app.safety.responses import assess_reliability, detect_conflicts
from app.verification.citations import normalise, stored_sources_from_retrieved, verify_citations

logger = logging.getLogger(__name__)

PROMPT_VERSION = "judge_support_case_brief.v1"
MAX_MODEL_ISSUES = 12

DISCLAIMER = (
    "This brief organises the material supplied for the court's convenience. "
    "It does not decide any issue or recommend an outcome; the decision rests "
    "with the court."
)

_DATE_FORMATS = (
    "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
    "%d %B %Y", "%d %b %Y", "%B %d, %Y", "%b %d, %Y", "%B %d %Y",
)


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    text = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", value.strip(), flags=re.IGNORECASE)
    text = text.replace(",", ", ").replace("  ", " ").strip()
    for fmt in _DATE_FORMATS:
        for candidate in (text, text.replace(", ", " ")):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                continue
    for fmt in ("%B %Y", "%b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    if re.fullmatch(r"\d{4}", text):
        return date(int(text), 1, 1)
    return None


@dataclass
class CaseBrief:
    facts: list[dict[str, Any]]
    chronology: list[dict[str, Any]]
    undated_fact_ids: list[str]
    disputed_issues: list[dict[str, Any]]
    party_arguments: list[dict[str, Any]]
    neutral_summary: str
    legal_sources: list[dict[str, Any]] = field(default_factory=list)
    verification: dict[str, Any] = field(default_factory=dict)
    conflicts: list[dict[str, Any]] = field(default_factory=list)
    neutrality: dict[str, Any] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    status: str = "completed"
    reliable: bool = False
    notice: str | None = None
    disclaimer: str = DISCLAIMER


# --------------------------------------------------------------------------- #
def _facts(facts_in: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for i, f in enumerate(facts_in, 1):
        parsed = parse_date(f.get("date"))
        out.append({
            "id": f"F{i}",
            "text": f["text"].strip(),
            "source_ref": f["source_ref"].strip(),
            "date": (f.get("date") or None),
            "date_iso": parsed.isoformat() if parsed else None,
            "disputed": bool(f.get("disputed")),
            "asserted_by": f.get("asserted_by"),
        })
    return out


def _chronology(facts: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[str]]:
    dated = [(f["date_iso"], i, f) for i, f in enumerate(facts) if f["date_iso"]]
    dated.sort(key=lambda t: (t[0], t[1]))
    chronology = [
        {
            "date": f["date"], "date_iso": iso, "fact_id": f["id"], "text": f["text"],
            "source_ref": f["source_ref"], "disputed": f["disputed"],
        }
        for iso, _, f in dated
    ]
    undated = [f["id"] for f in facts if not f["date_iso"]]
    return chronology, undated


def _party_arguments(parties_in: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out = []
    for p_index, party in enumerate(parties_in, 1):
        out.append({
            "party": party["name"].strip(),
            "role": party["role"].strip(),
            "arguments": [
                {
                    "id": f"P{p_index}-A{a_index}",
                    "text": arg["text"].strip(),
                    "source_ref": (arg.get("source_ref") or None),
                }
                for a_index, arg in enumerate(party["arguments"], 1)
            ],
        })
    return out


def _issue_text(fact_text: str) -> str:
    text = fact_text.strip().rstrip(".")
    return f"Whether it is established that {text[0].lower() + text[1:] if text else text}"


def _flagged_issues(facts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {"issue": _issue_text(f["text"]), "fact_ids": [f["id"]], "basis": "disputed_fact"}
        for f in facts if f["disputed"]
    ]


def _build_messages(case: dict[str, Any], facts, parties, sources) -> list[ChatMessage]:
    fact_lines = "\n".join(
        f"{f['id']} ({f['date'] or 'undated'}; source: {f['source_ref']}"
        f"{'; DISPUTED' if f['disputed'] else ''}): {f['text']}"
        for f in facts
    )
    party_lines = "\n\n".join(
        f"{p['party']} ({p['role']}):\n" + "\n".join(f"- {a['id']}: {a['text']}" for a in p["arguments"])
        for p in parties
    )
    instructions = (
        "Prepare a neutral case brief as a JSON object with exactly these keys:\n"
        '  "issues": a list of objects {"issue": string, "fact_ids": [fact ids]} - '
        "the issues the court must determine, each phrased as a neutral question "
        "starting with 'Whether', each linked to the fact ids it depends on;\n"
        '  "summary": a neutral summary (at most 200 words) of the dispute, '
        "the parties' positions in turn, and the applicable law from the SOURCES, "
        "citing sources as [n] and facts by their ids.\n"
        "Use only the fact ids listed. Do not decide any issue, assess which "
        "party is stronger, or recommend or predict an outcome."
    )
    user = (
        f"CASE: {case['case_title']}"
        f"{' (' + case['case_number'] + ')' if case.get('case_number') else ''}"
        f"{', ' + case['court'] if case.get('court') else ''}\n"
        f"{'QUESTION FROM THE COURT: ' + case['question'] if case.get('question') else ''}\n\n"
        f"FACTS:\n{fact_lines}\n\nPARTIES AND ARGUMENTS:\n{party_lines}\n\n"
        f"{format_sources(sources)}\n\n{instructions}"
    )
    return [
        ChatMessage("system", JudgeSupportAgent.system_prompt),
        ChatMessage("user", user),
    ]


def _parse_model_json(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        raise ValueError("no JSON object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("not an object")
    return data


def _fallback_summary(facts, parties, issues) -> str:
    disputed = sum(1 for f in facts if f["disputed"])
    names = " and ".join(f"{p['party']} ({p['role']})" for p in parties)
    return (
        f"This brief organises {len(facts)} fact(s), {disputed} of them disputed, "
        f"and the arguments of {names}. It lists {len(issues)} issue(s) for the "
        "court's determination. Each party's arguments are set out separately below."
    )


# --------------------------------------------------------------------------- #
def build_case_brief(
    case: dict[str, Any],
    *,
    gateway: ModelGateway,
    retriever: Callable[[str, dict], list[dict[str, Any]]] | None = None,
    top_k: int = 5,
) -> CaseBrief:
    facts = _facts(case["facts"])
    chronology, undated = _chronology(facts)
    parties = _party_arguments(case["parties"])
    fact_ids = {f["id"] for f in facts}
    warnings: list[str] = []

    # ---- legal sources ------------------------------------------------- #
    sources: list[dict[str, Any]] = []
    if retriever is not None:
        query = case.get("question") or (
            case["case_title"] + ". " + " ".join(f["text"] for f in facts if f["disputed"])[:600]
        )
        try:
            sources = list(retriever(query, {}))[:top_k]
        except Exception as exc:
            logger.warning("Case brief retrieval failed: %s", type(exc).__name__)
            warnings.append("retrieval_unavailable")

    # ---- issues + summary from the model -------------------------------- #
    issues = _flagged_issues(facts)
    summary = ""
    removed_count = 0
    try:
        result = gateway.generate(GenerationRequest(
            messages=_build_messages(case, facts, parties, sources),
            prompt_version=PROMPT_VERSION,
            purpose=f"{JUDGE_SUPPORT_AGENT}_case_brief",
            json_mode=True,
            max_output_tokens=1800,
        ))
        data = _parse_model_json(result.text)
        seen = {normalise(i["issue"]) for i in issues}
        for item in (data.get("issues") or [])[:MAX_MODEL_ISSUES]:
            if not isinstance(item, dict):
                continue
            text = str(item.get("issue") or "").strip()
            if not text or is_decisional(text):
                if text:
                    removed_count += 1
                continue
            ids = [str(x) for x in (item.get("fact_ids") or []) if str(x) in fact_ids]
            key = normalise(text)
            if key in seen:
                continue
            seen.add(key)
            issues.append({"issue": text, "fact_ids": ids, "basis": "model"})
        summary = str(data.get("summary") or "").strip()
    except ModelError as exc:
        warnings.append(exc.code)
    except (ValueError, TypeError) as exc:
        logger.warning("Case brief model output unusable: %s", type(exc).__name__)
        warnings.append("model_bad_response")

    by_id = {f["id"]: f for f in facts}
    disputed_issues = [
        {
            "id": f"I{i}",
            "issue": issue["issue"],
            "fact_ids": issue["fact_ids"],
            "source_refs": list(dict.fromkeys(by_id[fid]["source_ref"] for fid in issue["fact_ids"])),
            "basis": issue["basis"],
        }
        for i, issue in enumerate(issues, 1)
    ]

    if summary:
        checked = enforce_neutrality(summary)
        summary = checked.text
        removed_count += len(checked.removed)
    if not summary:
        summary = _fallback_summary(facts, parties, disputed_issues)

    # ---- citations, conflicts, reliability ------------------------------ #
    citations = citations_for(sources)
    report = verify_citations(summary, citations, stored_sources_from_retrieved(sources))
    conflicts = detect_conflicts(sources)
    degraded = any(w in warnings for w in ("retrieval_unavailable", "model_unavailable",
                                           "model_timeout", "model_bad_response"))
    status = "degraded" if degraded else "completed"
    reliability = assess_reliability(
        status=status, citations=citations, verification=report,
        conflicts=conflicts, warnings=warnings,
    )

    return CaseBrief(
        facts=facts,
        chronology=chronology,
        undated_fact_ids=undated,
        disputed_issues=disputed_issues,
        party_arguments=parties,
        neutral_summary=summary,
        legal_sources=report.annotate(citations),
        verification=report.summary(),
        conflicts=conflicts,
        neutrality={"checked": True, "removed_statements": removed_count},
        warnings=list(dict.fromkeys(warnings)),
        status=status,
        reliable=reliability.reliable,
        notice=reliability.notice,
    )
