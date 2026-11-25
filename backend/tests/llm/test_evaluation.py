"""SCRUM-19: evaluation against agreed criteria (fake model, no Ollama needed)."""

from app.llm.config import ModelSettings
from app.llm.evaluation import EvaluationCriteria, evaluate, load_cases
from app.llm.gateway import ModelGateway
from app.llm.providers.fake import FakeProvider
from app.llm.run_recorder import InMemoryRunRecorder
from app.llm.types import ModelUnavailableError

CASES = [
    {"id": "a", "system": "s", "prompt": "cheque", "expect": [["section 138"], ["notice"]]},
    {"id": "j", "kind": "json", "system": "s", "prompt": "recipe", "expected_intent": "out_of_scope"},
]


def gw(replies):
    return ModelGateway(ModelSettings(provider="fake", max_retries=0), provider=FakeProvider(replies),
                        recorder=InMemoryRunRecorder())


def test_passing_model():
    report = evaluate(gw(["Under Section 138 you get a notice.", '{"intent": "out_of_scope"}']), CASES)
    assert report["passed"] and report["metrics"]["content_pass_rate"] == 1.0


def test_evaluation_is_deterministic():
    gateway = gw(["Under Section 138 you get a notice.", '{"intent": "out_of_scope"}'])
    evaluate(gateway, CASES)
    requests = [call[0] for call in gateway.provider.calls]
    assert all(r.temperature == 0.0 and r.seed == 42 for r in requests)


def test_wrong_content_and_json_fail():
    report = evaluate(gw(["Something unrelated.", '{"intent": "legal_research"}']), CASES)
    assert not report["checks"]["content"] and not report["checks"]["json"]


def test_unavailable_model_fails_availability():
    report = evaluate(gw([ModelUnavailableError("down")] * 2), CASES)
    assert report["metrics"]["availability"] == 0 and not report["passed"]


def test_latency_limit():
    report = evaluate(gw(["Section 138 notice", '{"intent": "out_of_scope"}']), CASES,
                      EvaluationCriteria(max_p95_latency_ms=-1))
    assert not report["checks"]["latency"]


def test_bundled_cases_are_well_formed():
    cases = load_cases()
    assert len(cases) >= 10
    assert all({"id", "system", "prompt"} <= set(c) for c in cases)
