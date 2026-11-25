# Language model: Ollama + Qwen (SCRUM-19) and Model Gateway (SCRUM-20)

```
agents / orchestrator
        │  GenerationRequest
        ▼
  ModelGateway  ── retries, fallback model, timeouts, model_runs logging
        │
        ▼
  OllamaProvider ── POST /api/chat on Ollama (Qwen)
```

Agents depend only on `app.llm` (`ModelGateway`, `GenerationRequest`, `ChatMessage`,
`ModelError`), never on Ollama. You can switch models or providers by editing `.env`.

## 1. Install Ollama and pull Qwen

```bash
# https://ollama.com/download, then:
ollama pull qwen2.5:7b-instruct      # ~4.7 GB; use qwen2.5:3b-instruct on low-RAM machines
ollama serve                         # usually already running as a service
```

## 2. Configure (backend/.env)

| Variable | Default | Meaning |
|---|---|---|
| `LLM_PROVIDER` | `ollama` | `ollama`, or `fake` to run the API without a model |
| `LLM_OLLAMA_BASE_URL` (or `OLLAMA_BASE_URL`) | `http://localhost:11434` | Docker uses `http://host.docker.internal:11434` |
| `LLM_MODEL` (or `OLLAMA_MODEL`) | `qwen2.5:7b-instruct` | any pulled Ollama tag |
| `LLM_FALLBACK_MODEL` | empty | smaller model used if the main one fails |
| `LLM_TEMPERATURE` / `LLM_TOP_P` | `0.2` / `0.9` | generation defaults |
| `LLM_MAX_OUTPUT_TOKENS` / `LLM_CONTEXT_WINDOW` | `1024` / `8192` | |
| `LLM_CONNECT_TIMEOUT_SECONDS` / `LLM_REQUEST_TIMEOUT_SECONDS` | `5` / `120` | |
| `LLM_MAX_RETRIES` / `LLM_RETRY_BACKOFF_SECONDS` | `1` / `1.0` | retries for timeouts and unavailable server |
| `LLM_KEEP_ALIVE` | `10m` | how long Ollama keeps the model loaded |
| `LLM_RECORD_RUNS` | `true` | write a `model_runs` row per call |

## 3. Check it works

```bash
curl http://localhost:8000/api/v1/health/llm        # 200 when Ollama is up and the model is pulled
python scripts/evaluate_model.py --health-only       # same check from the command line
python scripts/evaluate_model.py                     # full evaluation (below)
```

## 4. Evaluation criteria (SCRUM-19)

`scripts/evaluate_model.py` runs the prompts in `eval_cases.json` (client, lawyer and judge
questions on Indian law, plus classifier JSON prompts). It writes a report to
`storage/evaluations/` and exits with code 1 if any criterion fails:

| Criterion | Default | Flag |
|---|---|---|
| Availability: every case answered | 100 % | |
| Content: answer mentions ≥ 50 % of expected legal concepts | ≥ 70 % of cases | `--min-content` |
| JSON: classifier prompts return valid JSON with the right intent | 100 % | |
| Latency: 95th percentile | ≤ 60 s (GPU target; agree a CPU limit, e.g. 90 s) | `--max-p95-ms` |

Runs use temperature 0 and a fixed seed, so the same model gives the same score every time. Compare models with `--model qwen2.5:3b-instruct` etc.

## 5. Using the gateway in an agent (SCRUM-20)

```python
from app.llm import ChatMessage, GenerationRequest, ModelError, get_model_gateway

try:
    result = get_model_gateway().generate(GenerationRequest(
        messages=[ChatMessage("system", "You are ..."), ChatMessage("user", question)],
        prompt_version="lawyer_agent.v2",   # stored in model_runs
        purpose="lawyer_agent",
    ))
except ModelError as exc:                    # model_unavailable | model_timeout | model_bad_response
    ...
result.text, result.model, result.run_id     # run_id -> model_runs.id, messages.model_run_id
```

How failures are handled:
* The gateway uses separate connect and read timeouts, then retries with exponential backoff
  (only timeouts and an unavailable server are retried).
* After that it tries `LLM_FALLBACK_MODEL` if one is set.
* Only `ModelError` subclasses reach callers. No raw `httpx` errors, URLs or stack traces get through.
* Every attempt, successful or failed, is recorded in `model_runs`. Each row holds the provider,
  the model tag, the prompt version, the parameters, the duration, the token counts and an error
  code. Prompt and answer text are not stored there.
  If the database is down, recording is skipped and logged, and the answer is still returned.
