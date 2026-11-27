"""SCRUM-25: Judge Support Agent - access, source-referenced facts, chronology,
disputed issues, separate party arguments, neutrality."""

import json
import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.agents.base import AgentContext
from app.agents.case_brief import build_case_brief, parse_date
from app.agents.default_agents import JudgeSupportAgent
from app.agents.neutrality import enforce_neutrality, is_decisional
from app.api import judge_support_routes
from app.api.assistant_routes import get_orchestrator
from app.api.dependencies import get_current_user
from app.db.session import get_db
from app.llm.config import ModelSettings
from app.llm.gateway import ModelGateway
from app.llm.providers.fake import FakeProvider
from app.llm.run_recorder import InMemoryRunRecorder
from app.llm.types import ModelUnavailableError
from app.main import app
from app.orchestration.state import INTENT_CASE_ANALYSIS


def gateway(replies=None):
    s = ModelSettings(provider="fake", max_retries=0, retry_backoff_seconds=0)
    return ModelGateway(s, provider=FakeProvider(replies), recorder=InMemoryRunRecorder(), sleep=lambda _: None)


SOURCES = [{
    "chunk_id": "c1", "text": "Section 138. Dishonour of cheque for insufficiency of funds in the account.",
    "source_title": "Negotiable Instruments Act, 1881", "citation": "Section 138", "section_ref": "Section 138",
}]

CASE = {
    "case_title": "A. Kumar v. B. Singh",
    "case_number": "CC 12/2024",
    "court": "Judicial Magistrate, Kochi",
    "question": None,
    "facts": [
        {"text": "The accused issued cheque no. 4471 for Rs 2,00,000.", "source_ref": "Exhibit P-1",
         "date": "12/03/2024", "disputed": False},
        {"text": "The complainant sent a demand notice.", "source_ref": "Exhibit P-3, para 2",
         "date": "2024-04-20", "disputed": False},
        {"text": "The cheque was returned unpaid for insufficient funds.", "source_ref": "Exhibit P-2",
         "date": "1 April 2024", "disputed": False},
        {"text": "The demand notice was received by the accused.", "source_ref": "Postal receipt, Exhibit P-4",
         "date": None, "disputed": True, "asserted_by": "Complainant"},
    ],
    "parties": [
        {"name": "A. Kumar", "role": "Complainant",
         "arguments": [{"text": "All ingredients of Section 138 are made out.", "source_ref": "Complaint para 7"}]},
        {"name": "B. Singh", "role": "Accused",
         "arguments": [{"text": "No notice was received, so the offence is incomplete.", "source_ref": "Reply para 3"}]},
    ],
}


def model_reply(issues=None, summary=None):
    return json.dumps({
        "issues": issues if issues is not None else [
            {"issue": "Whether the cheque was presented within its validity period", "fact_ids": ["F1", "F3", "F99"]},
            {"issue": "The accused is guilty and should be convicted", "fact_ids": ["F4"]},
        ],
        "summary": summary if summary is not None else (
            "The complainant relies on the dishonoured cheque (F1, F3) and Section 138 [1]. "
            "The accused disputes receipt of the notice (F4). The accused is clearly liable."
        ),
    })


# ------------------------------------------------------------------ neutrality
@pytest.mark.parametrize("sentence", [
    "The petition should be dismissed.",
    "I recommend that the court grant bail.",
    "The accused is guilty of the offence.",
    "The court should convict the accused.",
    "The petitioner has the stronger case.",
    "The likely outcome is an acquittal.",
    "The respondent is likely to succeed.",
    "Judgment in favour of the plaintiff is appropriate.",
])
def test_decisional_language_is_detected(sentence):
    assert is_decisional(sentence)


@pytest.mark.parametrize("sentence", [
    "The court must decide whether the notice was served.",
    "Whether the accused is liable under Section 138 is an issue for determination.",
    "The complainant argues that the cheque was dishonoured.",
    "The court should consider the postal receipt.",
])
def test_neutral_language_is_kept(sentence):
    assert not is_decisional(sentence)


def test_enforce_neutrality_removes_and_notes():
    result = enforce_neutrality("Facts are as follows. The appeal should be allowed.")
    assert "should be allowed" not in result.text
    assert "Facts are as follows." in result.text
    assert "decision rests with the court" in result.text
    assert len(result.removed) == 1


# ------------------------------------------------------------------ case brief
def test_brief_keeps_source_references_and_builds_chronology():
    brief = build_case_brief(CASE, gateway=gateway([model_reply()]), retriever=lambda q, s: SOURCES)

    assert [f["source_ref"] for f in brief.facts] == [f["source_ref"] for f in CASE["facts"]]
    assert [c["fact_id"] for c in brief.chronology] == ["F1", "F3", "F2"]  # sorted by date
    assert [c["date_iso"] for c in brief.chronology] == ["2024-03-12", "2024-04-01", "2024-04-20"]
    assert all(c["source_ref"] for c in brief.chronology)
    assert brief.undated_fact_ids == ["F4"]


def test_brief_generates_disputed_issues_with_valid_fact_links():
    brief = build_case_brief(CASE, gateway=gateway([model_reply()]), retriever=lambda q, s: SOURCES)
    issues = brief.disputed_issues

    flagged = [i for i in issues if i["basis"] == "disputed_fact"]
    assert flagged and flagged[0]["fact_ids"] == ["F4"]
    assert flagged[0]["source_refs"] == ["Postal receipt, Exhibit P-4"]

    model = [i for i in issues if i["basis"] == "model"]
    assert len(model) == 1  # the decisional "issue" was dropped
    assert model[0]["fact_ids"] == ["F1", "F3"]  # unknown F99 dropped
    assert "Exhibit P-1" in model[0]["source_refs"]
    assert all(not is_decisional(i["issue"]) for i in issues)


def test_party_arguments_are_kept_separate():
    brief = build_case_brief(CASE, gateway=gateway([model_reply()]), retriever=lambda q, s: SOURCES)
    parties = brief.party_arguments
    assert [p["party"] for p in parties] == ["A. Kumar", "B. Singh"]
    assert parties[0]["arguments"][0]["id"] == "P1-A1"
    assert "Section 138" in parties[0]["arguments"][0]["text"]
    assert "No notice" in parties[1]["arguments"][0]["text"]
    assert parties[1]["arguments"][0]["source_ref"] == "Reply para 3"


def test_summary_stays_neutral():
    brief = build_case_brief(CASE, gateway=gateway([model_reply()]), retriever=lambda q, s: SOURCES)
    assert "clearly liable" not in brief.neutral_summary
    assert "decision rests with the court" in brief.neutral_summary
    assert brief.neutrality["removed_statements"] == 2  # one issue + one summary sentence
    assert brief.legal_sources[0]["verification_status"] == "verified"
    assert "does not decide" in brief.disclaimer


def test_brief_survives_model_outage():
    brief = build_case_brief(CASE, gateway=gateway([ModelUnavailableError("down")]),
                             retriever=lambda q, s: SOURCES)
    assert brief.status == "degraded"
    assert "model_unavailable" in brief.warnings
    assert brief.reliable is False
    assert len(brief.chronology) == 3
    assert brief.disputed_issues[0]["fact_ids"] == ["F4"]
    assert "A. Kumar" in brief.neutral_summary


def test_brief_handles_bad_model_json():
    brief = build_case_brief(CASE, gateway=gateway(["not json at all"]), retriever=None)
    assert "model_bad_response" in brief.warnings
    assert brief.neutral_summary


@pytest.mark.parametrize("raw, iso", [
    ("2024-03-12", "2024-03-12"), ("12/03/2024", "2024-03-12"), ("12-03-2024", "2024-03-12"),
    ("12th March 2024", "2024-03-12"), ("March 12, 2024", "2024-03-12"), ("Mar 2024", "2024-03-01"),
])
def test_date_parsing(raw, iso):
    assert parse_date(raw).isoformat() == iso


def test_chat_agent_output_is_neutral():
    agent = JudgeSupportAgent()
    ctx = AgentContext(message="Summarise the arguments", intent=INTENT_CASE_ANALYSIS,
                       user_roles=frozenset({"JUDGE"}), sources=SOURCES)
    result = agent.run(ctx, gateway(["Both sides rely on Section 138 [1]. The complaint should be allowed."]))
    assert "should be allowed" not in result.content
    assert result.metadata["neutrality"]["removed_statements"] == 1


def test_chat_agent_requires_evidence():
    ctx = AgentContext(message="Summarise", intent=INTENT_CASE_ANALYSIS, user_roles=frozenset({"JUDGE"}))
    result = JudgeSupportAgent().run(ctx, gateway(["must not be called"]))
    assert result.metadata["safe_fallback"] is True


# ------------------------------------------------------------------ API access
def make_user(role):
    return SimpleNamespace(id=uuid.uuid4(), is_active=True,
                           role_assignments=[SimpleNamespace(role=SimpleNamespace(code=role))])


@pytest.fixture
def client(monkeypatch):
    orch = SimpleNamespace(gateway=gateway([model_reply()]))
    app.dependency_overrides[get_db] = lambda: None
    app.dependency_overrides[get_orchestrator] = lambda: orch
    monkeypatch.setattr(judge_support_routes, "_make_retriever", lambda db, user: (lambda q, s: SOURCES))
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.mark.parametrize("role", ["CLIENT", "LAWYER"])
def test_only_authorized_users_can_use_workspace(client, role):
    app.dependency_overrides[get_current_user] = lambda: make_user(role)
    r = client.post("/api/v1/judge-support/case-brief", json=CASE)
    assert r.status_code == 403
    assert "Judge Support" in r.json()["detail"]


@pytest.mark.parametrize("role", ["JUDGE", "ADMIN"])
def test_judge_gets_case_brief(client, role):
    app.dependency_overrides[get_current_user] = lambda: make_user(role)
    r = client.post("/api/v1/judge-support/case-brief", json=CASE)
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["chronology"]) == 3
    assert len(body["party_arguments"]) == 2
    assert body["facts"][3]["source_ref"] == "Postal receipt, Exhibit P-4"
    assert body["neutrality"]["checked"] is True
    assert "audit_not_saved" in body["warnings"]  # no DB in this test


def test_facts_require_source_reference(client):
    app.dependency_overrides[get_current_user] = lambda: make_user("JUDGE")
    bad = {**CASE, "facts": [{"text": "Something happened.", "source_ref": ""}]}
    assert client.post("/api/v1/judge-support/case-brief", json=bad).status_code == 422


def test_two_parties_required(client):
    app.dependency_overrides[get_current_user] = lambda: make_user("JUDGE")
    bad = {**CASE, "parties": CASE["parties"][:1]}
    assert client.post("/api/v1/judge-support/case-brief", json=bad).status_code == 422
