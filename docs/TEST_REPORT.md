# LawPilot AI – System and Security Test Report (SCRUM-30)

**Date:** 27 November 2026 · **Branch:** `feature/llm-orchestration` (master merged on 26 Nov) · **Tester:** Jiss K Thomas

## Result

**487 automated tests pass, 0 fail, 27 skipped.** The 25 skipped tests need the Docker PC
(PostgreSQL + Qdrant) or the real OCR model and must be run before release (see *Not yet run*).

| Area | Tests | Result | Where |
| --- | --- | --- | --- |
| System and security (auth, roles, uploads, agent workflows, failures) | 62 | Pass | `tests/system/` |
| Safe responses (reliability, conflicts, secrets, error handling) | 19 | Pass | `tests/safety/` |
| Citation verification | 16 | Pass | `tests/verification/` |
| Agents (lawyer, judge support, neutrality, case brief) | 37 | Pass | `tests/agents/` |
| Orchestrator and assistant API | 41 | Pass | `tests/orchestration/` |
| Model gateway, Ollama provider, evaluation | 35 | Pass | `tests/llm/` |
| Ingestion (extraction, OCR, chunking, indexing) | 124 pass, 1 skipped | Pass | `tests/ingestion/` |
| Auth, RBAC, drafts, retrieval, ranking, filters | 130 | Pass | `tests/test_*.py` |
| Database integration (real PostgreSQL) | 24 skipped | Not run | `tests/integration/` |
| Frontend build and lint | build OK, 4 old lint errors | Pass with notes | `frontend/` |

How to repeat: `cd backend && pytest` (unit + system), then with the Docker PC on:
`TEST_DATABASE_URL=postgresql+psycopg://legal_ai_user:local_dev_password@localhost:5432/legal_ai pytest`.
Frontend: `cd frontend && npm run lint && npm run build`.

## Acceptance criteria

| Criterion | Evidence | Status |
| --- | --- | --- |
| Authentication and role restrictions work correctly | 16 protected endpoints return 401 without a token; forged, unsigned (`alg: none`), expired and malformed tokens are refused; deleted, deactivated and unverified accounts are refused; 9 endpoint groups refuse every wrong role with 403; the frontend `RequireRole` guard sends users to their own workspace | Pass |
| Unauthorized document uploads are rejected | Clients, lawyers and judges get 403; no token gets 401; admins uploading `.exe`, `.docx`, a wrong content type, or HTML renamed to `.pdf` get 400 | Pass |
| All three agent workflows are tested | Client, Lawyer and Judge Support each answer end to end through `POST /api/v1/assistant/chat` with verified citations; 5 role/agent combinations that are not allowed return 403; `/assistant/agents` lists only permitted agents | Pass |
| Retrieval and citation verification work correctly | Hybrid retrieval unit tests; 16 citation-verification tests (missing source, bad reference number, wrong title, old edition, missing locator, invented quote); answers with failed citations are marked unreliable | Pass (live retrieval: run integration tests) |
| Model and database failures are handled safely | Model outage returns a plain "temporarily unavailable" answer marked unreliable; a database outage returns a generic 500 with a request ID and no connection string, password, host or stack trace; chat still answers when saving the conversation fails | Pass |
| Test results and defects are documented | This report | Done |

## Defects found

| ID | Severity | Defect | Status |
| --- | --- | --- | --- |
| D0 | High | Found in manual testing: an answer about bail named "Sections 462 and 463 of the Code of Criminal Procedure, 1974", which are not in any retrieved source (the sources were Contract Act bailment sections), yet it was shown as reliable because the cited source existed | Fixed: every section, article and Act named in an answer must appear in the retrieved sources (`app/verification/provisions.py`); otherwise the answer is marked unreliable and the notice names the unsupported law |
| D1 | High | Draft export only needed the author's own review; no second-person approval | Fixed (SCRUM-24) |
| D2 | High | Form validation errors echoed back submitted values, including passwords | Fixed (SCRUM-27, `app/main.py`) |
| D3 | Medium | Any signed-in user could open `/admin` pages by URL (the API already blocked their data) | Fixed (`RequireRole`, SCRUM-28) |
| D4 | Medium | When the knowledge base was down, answers said "no sources found" instead of "search unavailable" | Fixed (SCRUM-27) |
| D5 | Medium | Frontend ignored `VITE_API_BASE_URL` and always called `localhost:8000` | Fixed (`frontend/src/services/api.js`) |
| D6 | Medium | An expired session left screens half-loaded | Fixed (401 interceptor sends the user to login) |
| D7 | Low | Ollama settings test failed when a developer `.env` was present | Fixed (test isolation) |
| D8 | Medium | No rate limit or lockout on `POST /api/v1/auth/login` (brute-force risk) | Open – recommend for next sprint |
| D9 | Medium | CORS only allows `http://localhost:517x`; a deployed frontend on another host will be blocked | Open – set before deployment |
| D10 | Medium | Model latency on CPU: p95 about 82 s, above the original 60 s target (90 s agreed for CPU) | Open – accepted for MVP; GPU recommended |
| D11 | Medium | Model content accuracy is borderline: 75 % against a 70 % target; `cheque_bounce` and `tenant_eviction` cases fail in the latest run | Open – see `EVALUATION.md` |
| D12 | Low | `app/db/session.py` calls `load_dotenv()`, which copies `.env` into the process environment (cause of D7) | Open |
| D13 | Low | Access token is kept in `localStorage`, readable by any injected script | Accepted risk for MVP |
| D14 | Low | 4 lint errors (setState inside effects) in `AdminLegalSources`, `AdminOverview`, `AdminUsers` (existed before this sprint) | Open |
| D15 | High | Assistant answered from model memory when the uploaded documents did not cover the question (e.g. named IPC s.302 / BNS s.262 with only Contract Act sources) | Fixed: source-only prompt with a `NO_ANSWER_AVAILABLE` signal, plus a hard gate that replaces any answer naming law not in the sources, or citing no source, with "No answer available" (`tests/safety/test_grounding_gate.py`) |

## Not yet run

These need the Docker PC and Ollama, and are on the release checklist:

1. Database integration tests (24) with `TEST_DATABASE_URL`.
2. `alembic upgrade head` on the real database (offline check passed, see `MIGRATIONS.md`).
3. `python scripts/smoke_test.py` against the running backend.
4. Manual walk-through of every role in the browser (checklist in `RELEASE.md`).
