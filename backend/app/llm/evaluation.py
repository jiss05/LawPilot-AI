"""
Model evaluation (SCRUM-19: "Model performance is evaluated against agreed criteria").

Runs a fixed set of Indian-law prompts through the ModelGateway and checks
the results against these criteria (defaults below; change them in
EvaluationCriteria or with command-line flags of scripts/evaluate_model.py):

    availability     every case gets an answer (no errors/timeouts)      100 %
    content          answer mentions the expected legal concepts          >= 70 % of cases
    json             classifier prompt returns valid JSON + valid intent  100 %
    latency          95th percentile response time                        <= 60 s
                     (GPU target; on CPU-only hardware agree a limit, e.g. 90 s)

Generation is deterministic (temperature 0, fixed seed) so the same model
gives the same score on every run and models can be compared fairly.

Each expected concept is a group of alternatives, e.g. ["section 138", "s. 138"];
a case passes when at least `min_concepts_ratio` of its groups appear.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.llm.gateway import ModelGateway, parse_json_object
from app.llm.types import ChatMessage, GenerationRequest, ModelError
from app.orchestration.state import INTENTS

CASES_FILE = Path(__file__).with_name("eval_cases.json")
EVAL_TEMPERATURE = 0.0
EVAL_SEED = 42


@dataclass
class EvaluationCriteria:
    min_availability: float = 1.0
    min_content_pass_rate: float = 0.7
    min_json_pass_rate: float = 1.0
    max_p95_latency_ms: int = 60_000
    min_concepts_ratio: float = 0.5


@dataclass
class CaseResult:
    id: str
    kind: str
    ok: bool
    passed: bool
    duration_ms: int | None = None
    completion_tokens: int | None = None
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)
    error: str | None = None


def load_cases(path: Path = CASES_FILE) -> list[dict[str, Any]]:
    return json.loads(path.read_text(encoding="utf-8"))


def _concepts(answer: str, groups: list[list[str]]) -> tuple[list[str], list[str]]:
    text = answer.lower()
    matched, missing = [], []
    for group in groups:
        (matched if any(alt.lower() in text for alt in group) else missing).append(group[0])
    return matched, missing


def run_case(gateway: ModelGateway, case: dict, criteria: EvaluationCriteria) -> CaseResult:
    kind = case.get("kind", "answer")
    messages = [ChatMessage("system", case["system"]), ChatMessage("user", case["prompt"])]
    request = GenerationRequest(messages=messages, prompt_version="evaluation.v1",
                                json_mode=(kind == "json"), purpose="evaluation",
                                temperature=EVAL_TEMPERATURE, seed=EVAL_SEED)
    try:
        result = gateway.generate(request)
    except ModelError as exc:
        return CaseResult(id=case["id"], kind=kind, ok=False, passed=False, error=exc.code)

    base = dict(id=case["id"], kind=kind, ok=True, duration_ms=result.duration_ms,
                completion_tokens=result.completion_tokens)
    if kind == "json":
        try:
            intent = str(parse_json_object(result.text).get("intent", "")).lower()
        except ModelError:
            return CaseResult(**base, passed=False, error="invalid_json")
        expected = case.get("expected_intent")
        passed = intent in INTENTS and (expected is None or intent == expected)
        return CaseResult(**base, passed=passed, matched=[intent] if passed else [],
                          missing=[] if passed else [expected or "valid intent"])

    matched, missing = _concepts(result.text, case.get("expect", []))
    total = len(matched) + len(missing)
    passed = total == 0 or len(matched) / total >= criteria.min_concepts_ratio
    return CaseResult(**base, passed=passed, matched=matched, missing=missing)


def evaluate(gateway: ModelGateway, cases: list[dict] | None = None,
             criteria: EvaluationCriteria | None = None) -> dict[str, Any]:
    criteria = criteria or EvaluationCriteria()
    cases = cases if cases is not None else load_cases()
    results = [run_case(gateway, c, criteria) for c in cases]

    answered = [r for r in results if r.ok]
    content = [r for r in results if r.kind == "answer"]
    json_cases = [r for r in results if r.kind == "json"]
    durations = sorted(r.duration_ms for r in answered if r.duration_ms is not None)

    def rate(items):
        return round(sum(r.passed for r in items) / len(items), 3) if items else 1.0

    p95 = durations[min(len(durations) - 1, int(round(0.95 * (len(durations) - 1))))] if durations else None
    metrics = {
        "availability": round(len(answered) / len(results), 3) if results else 0.0,
        "content_pass_rate": rate(content),
        "json_pass_rate": rate(json_cases),
        "p50_latency_ms": int(statistics.median(durations)) if durations else None,
        "p95_latency_ms": p95,
    }
    checks = {
        "availability": metrics["availability"] >= criteria.min_availability,
        "content": metrics["content_pass_rate"] >= criteria.min_content_pass_rate,
        "json": metrics["json_pass_rate"] >= criteria.min_json_pass_rate,
        "latency": p95 is not None and p95 <= criteria.max_p95_latency_ms,
    }
    return {
        "provider": gateway.provider.name,
        "model": gateway.settings.model,
        "criteria": asdict(criteria),
        "metrics": metrics,
        "checks": checks,
        "passed": all(checks.values()),
        "cases": [asdict(r) for r in results],
    }
