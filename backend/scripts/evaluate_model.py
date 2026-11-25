"""
Check that Ollama + Qwen work and meet the agreed criteria (SCRUM-19).

Run from backend/ with Ollama running and the model pulled:

    ollama pull qwen2.5:7b-instruct
    python scripts/evaluate_model.py
    python scripts/evaluate_model.py --model qwen2.5:3b-instruct --max-p95-ms 30000
    python scripts/evaluate_model.py --health-only

Writes a JSON report to storage/evaluations/ and exits with code 1 if any
criterion fails, so it can be used in CI or before a demo.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

from app.llm.config import ModelSettings  # noqa: E402
from app.llm.evaluation import EvaluationCriteria, evaluate  # noqa: E402
from app.llm.gateway import ModelGateway  # noqa: E402
from app.llm.run_recorder import InMemoryRunRecorder  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--model", help="Ollama model tag (default: LLM_MODEL from .env)")
    parser.add_argument("--base-url", help="Ollama URL (default: LLM_OLLAMA_BASE_URL from .env)")
    parser.add_argument("--health-only", action="store_true", help="only check the server and model")
    parser.add_argument("--max-p95-ms", type=int, help="latency limit for the 95th percentile")
    parser.add_argument("--min-content", type=float, help="minimum share of content cases that must pass")
    parser.add_argument("--out", type=Path, help="report path (default: storage/evaluations/<model>-<time>.json)")
    args = parser.parse_args()

    overrides = {"record_runs": False, "max_retries": 0}
    if args.model:
        overrides["model"] = args.model
    if args.base_url:
        overrides["ollama_base_url"] = args.base_url
    settings = ModelSettings(**overrides)
    gateway = ModelGateway(settings, recorder=InMemoryRunRecorder())

    health = gateway.health()
    print(f"Ollama: {health.get('status')}  model: {settings.model}  "
          f"server: {health.get('server_version', '-')}")
    if health.get("status") != "ok":
        print(health.get("hint") or "Start Ollama (`ollama serve`) and check LLM_OLLAMA_BASE_URL.")
        return 1
    if args.health_only:
        return 0

    criteria = EvaluationCriteria()
    if args.max_p95_ms:
        criteria.max_p95_latency_ms = args.max_p95_ms
    if args.min_content is not None:
        criteria.min_content_pass_rate = args.min_content

    print("Running evaluation cases (this can take a few minutes on CPU)...")
    report = evaluate(gateway, criteria=criteria)
    for case in report["cases"]:
        mark = "PASS" if case["passed"] else "FAIL"
        detail = case["error"] or (f"missing: {', '.join(case['missing'])}" if case["missing"] else "")
        print(f"  {mark}  {case['id']:<24} {case['duration_ms'] or '-':>7} ms  {detail}")
    m = report["metrics"]
    print(f"\navailability {m['availability']:.0%}  content {m['content_pass_rate']:.0%}  "
          f"json {m['json_pass_rate']:.0%}  p50 {m['p50_latency_ms']} ms  p95 {m['p95_latency_ms']} ms")
    for name, ok in report["checks"].items():
        print(f"  {'OK  ' if ok else 'FAIL'} {name}")

    out = args.out or BACKEND / "storage" / "evaluations" / (
        f"{settings.model.replace(':', '_').replace('/', '_')}-{datetime.now():%Y%m%d-%H%M%S}.json")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nReport: {out}")
    print("RESULT:", "PASSED" if report["passed"] else "FAILED")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
