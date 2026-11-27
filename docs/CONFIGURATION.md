# LawPilot AI – Configuration

All backend settings are environment variables, read from `backend/.env` (copy
`backend/.env.example`). Never commit `.env`; it holds secrets. Values below are the defaults.

## Required

| Variable | Example | Notes |
| --- | --- | --- |
| `JWT_SECRET_KEY` | 64 random characters | **The backend does not start without it.** Generate with `python -c "import secrets; print(secrets.token_urlsafe(48))"`. Changing it signs everyone out. |
| `DATABASE_URL` | `postgresql+psycopg://legal_ai_user:local_dev_password@localhost:5432/legal_ai` | Docker overrides the host to `postgres`. |

## Application and authentication

| Variable | Default | Notes |
| --- | --- | --- |
| `APP_NAME` | `LawPilot AI` | |
| `APP_ENV` | `development` | |
| `JWT_ALGORITHM` | `HS256` | |
| `ACCESS_TOKEN_EXPIRE_MINUTES` | `30` | Users are sent to the login page when it expires. |

## Email (registration OTP and password reset)

| Variable | Default | Notes |
| --- | --- | --- |
| `EMAIL_HOST` / `EMAIL_PORT` | `smtp.gmail.com` / `587` | |
| `EMAIL_USERNAME` / `EMAIL_PASSWORD` | empty | Gmail needs an app password. See `backend/OTP_SETUP.md`. |
| `EMAIL_FROM` | `EMAIL_USERNAME` | |
| `EMAIL_USE_TLS` | `true` | |
| `SMTP_TIMEOUT_SECONDS` | `15` | |
| `OTP_EXPIRE_MINUTES` | `5` | |
| `OTP_MAX_ATTEMPTS` | `5` | Wrong codes allowed before the code is void. |
| `OTP_RESEND_COOLDOWN_SECONDS` | `60` | |

## Model (Ollama + Qwen)

| Variable | Default | Notes |
| --- | --- | --- |
| `LLM_PROVIDER` | `ollama` | `fake` runs without a model (canned answers, for development). |
| `LLM_OLLAMA_BASE_URL` | `http://localhost:11434` | Old name `OLLAMA_BASE_URL` also works. Docker uses `http://host.docker.internal:11434`. |
| `LLM_MODEL` | `qwen2.5:7b-instruct` | Old name `OLLAMA_MODEL` also works. Pull it with `ollama pull`. |
| `LLM_FALLBACK_MODEL` | empty | Used when the main model fails. |
| `LLM_TEMPERATURE` | `0.2` | |
| `LLM_MAX_OUTPUT_TOKENS` | `1024` | Agents set their own limits per task. |
| `LLM_CONTEXT_WINDOW` | `8192` | |
| `LLM_REQUEST_TIMEOUT_SECONDS` | `120` | Raise on slow CPUs. |
| `LLM_CONNECT_TIMEOUT_SECONDS` | `5` | |
| `LLM_MAX_RETRIES` | `1` | |
| `LLM_RECORD_RUNS` | `true` | Logs each call to `model_runs` (no prompt or answer text). Feeds the monitoring dashboard. |

More detail: `backend/app/llm/README.md`.

## Vector store, ingestion and retrieval

| Variable | Default | Notes |
| --- | --- | --- |
| `QDRANT_URL` | `http://localhost:6333` | Docker overrides it to `http://qdrant:6333`. |
| `QDRANT_API_KEY` | empty | |
| `INGESTION_QDRANT_COLLECTION` | `legal_chunks_v1` | |
| `INGESTION_EMBEDDING_PROVIDER` | `sentence-transformers` | |
| `INGESTION_EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | 384 dimensions. Changing it needs re-indexing. |
| `INGESTION_OCR_ENABLED` | `true` | EasyOCR for scanned pages. |
| `INGESTION_OCR_LANGUAGES` | `["en"]` | |
| `INGESTION_CHUNK_MAX_TOKENS` | `400` | |
| `INGESTION_CHUNK_OVERLAP_TOKENS` | `50` | |
| `INGESTION_STORAGE_DIR` | `backend/legal_documents` | Uploaded originals. |
| `INGESTION_EXTRACTED_DIR` | `backend/storage/extracted` | Extracted page text. |

More detail: `backend/app/ingestion/README.md`.

## Frontend

| Variable | Default | Notes |
| --- | --- | --- |
| `VITE_API_BASE_URL` | `http://localhost:8000` | Backend address, without `/api/v1`. Set it in `frontend/.env` before `npm run build` for any other host. |

## Not configurable yet

- **CORS:** `app/main.py` allows only `http://localhost:5170`–`5179` and `http://127.0.0.1:517x`. Change
  `allow_origin_regex` before deploying the frontend on another host (defect D9).
- **Upload limit:** 20 MB per PDF, set in `app/api/knowledge_source_routes.py`.
