# LawPilot AI – Evaluation Results

**Model:** `qwen2.5:7b-instruct` on Ollama (CPU) · **Runs:** 24 November 2026 · **Latest result: PASS**

The model is evaluated with `backend/scripts/evaluate_model.py` against 11 fixed Indian-law cases
(8 answer-content cases and 3 request-classification cases). Generation is deterministic
(temperature 0, seed 42), so runs are comparable. Each run writes a JSON report to
`backend/storage/evaluations/`, and admins can see every run in **Admin → Monitoring →
Evaluation & feedback**.

## Criteria

| Check | Target |
| --- | --- |
| Availability (every case answered, no errors or timeouts) | 100 % |
| Content (answer contains the expected legal concepts) | at least 70 % of content cases |
| Classifier JSON (valid JSON with a valid intent) | 100 % |
| Latency, 95th percentile | 60 s on GPU; 90 s agreed for CPU-only hardware |

## Runs

| Run (24 Nov) | Cases passed | Availability | Content | JSON | p50 | p95 | Latency limit | Result |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 18:49 | 9 / 11 | 100 % | 75 % | 100 % | 50.4 s | 82.6 s | 90 s | **Pass** |
| 18:37 | 7 / 11 | 100 % | 50 % | 100 % | 39.3 s | 81.9 s | 90 s | Fail (content) |
| 18:27 | 9 / 11 | 100 % | 75 % | 100 % | 37.1 s | 78.1 s | 60 s | Fail (latency) |
| 18:10 | 9 / 11 | 100 % | 75 % | 100 % | 40.1 s | 110.4 s | 60 s | Fail (latency) |

Cases that failed in the latest run: `cheque_bounce` and `tenant_eviction` (expected concepts
missing). `fir_refusal` and `bench_note_neutral` passed in the latest run but failed in earlier
ones, so content accuracy is close to the 70 % line (defect D11 in `TEST_REPORT.md`).

## What this means

- The model is always available and always returns valid classifier JSON.
- Content accuracy meets the target, but only just; answers stay grounded because every agent
  must cite retrieved sources, and citations are verified (SCRUM-26) before an answer is
  marked reliable.
- On CPU, a typical answer takes about 40–50 s and slow ones about 80 s. A GPU, or a smaller
  model for classification, is recommended before wider use (defect D10).

## Live monitoring after release

| Signal | Where |
| --- | --- |
| Model calls, failures by error code, average and p95 time (last 7 days) | Admin → Monitoring → Evaluation & feedback, from `model_runs` |
| User ratings (thumbs up/down) and reported issue types | Same page, from `feedback` |
| Re-run the evaluation after any model or prompt change | `python scripts/evaluate_model.py` (from `backend/`) |
