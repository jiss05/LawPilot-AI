# LawPilot AI – API Reference

Base URL: `http://localhost:8000` · All business endpoints are under `/api/v1` · Format: JSON.
The live, interactive version of this reference (try requests in the browser) is at
**http://localhost:8000/docs**. The full machine-readable spec is in [`openapi.json`](openapi.json),
generated from the code on 27 Nov 2026 (48 paths, 55 operations).

## Authentication

1. `POST /api/v1/auth/register`, then `POST /api/v1/auth/verify-email` with the emailed OTP.
2. `POST /api/v1/auth/login` returns an `access_token`.
3. Send it on every other request: `Authorization: Bearer <access_token>`.

Tokens expire after `ACCESS_TOKEN_EXPIRE_MINUTES` (default 30). Roles are read from the
database on every request, never from the request body.

## Who can call what

| Area | CLIENT | LAWYER | JUDGE | ADMIN |
| --- | --- | --- | --- | --- |
| Assistant chat, agents list, feedback | client agent | lawyer + client agents | judge support agent | all agents |
| Research search | yes | yes | yes | yes |
| Citation verification | yes | yes | yes | yes |
| Matters and drafts | – | yes (approve only as a reviewer who is not the author) | – | – |
| Judge Support case brief | – | – | yes | yes |
| Legal source upload, versions, activation, delete | – (can list sources) | – (can list sources) | – (can list sources) | yes |
| Admin: users, ingestion, audit, evaluation, feedback | – | – | – | yes |

A request without a valid token gets **401**; a valid token with the wrong role gets **403**.

## Errors

Errors are JSON `{"detail": ...}` with an `X-Request-ID` header. Validation errors (422) list
`loc`, `msg` and `type` and never repeat the submitted values. Unexpected errors (500) return a
fixed message and the `request_id`, never a stack trace or internal details.

## Key responses

**`POST /api/v1/assistant/chat`** returns `answer`, `answered_by`, `status`
(`completed | degraded | rejected | failed`), **`reliable`** (true only when every cited source
verified and sources do not conflict), `notice` (why not reliable), `citations[]` (each with
`verification_status`: `verified | failed | not_cited | unverified`), `verification`,
`conflicts`, `warnings` and `message_id` (for feedback).

**Drafts** move `draft → reviewed → approved → exported`. Every draft carries
`requires_human_review`, `can_approve` (for the caller), `citations_verified` and
`invalid_references`.

**`POST /api/v1/judge-support/case-brief`** returns `facts`, `chronology`, `undated_fact_ids`,
`disputed_issues`, `party_arguments`, `neutral_summary`, `legal_sources`, `neutrality`,
`reliable`, `notice` and `disclaimer`.

## All endpoints

### General

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/` | Root |
| GET | `/health` | Health Check |

### Authentication

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | Register |
| POST | `/api/v1/auth/verify-email` | Verify Email |
| POST | `/api/v1/auth/resend-otp` | Resend Otp |
| POST | `/api/v1/auth/login` | Login |
| POST | `/api/v1/auth/forgot-password` | Forgot Password |
| POST | `/api/v1/auth/reset-password` | Reset Password Endpoint |

### Users

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/v1/users/me` | Return the profile of the currently logged-in user. |
| POST | `/api/v1/users/me/change-password` | Change the password of the currently authenticated user. |
| GET | `/api/v1/users/admin/list` | Return users for Admin User Management. |

### Dashboards

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/v1/client/dashboard` | Client Dashboard |
| GET | `/api/v1/lawyer/dashboard` | Lawyer Dashboard |
| GET | `/api/v1/judge/dashboard` | Judge Dashboard |
| GET | `/api/v1/admin/dashboard` | Admin Dashboard |

### Legal Source Registry

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/v1/knowledge-sources` | List Legal Sources |
| POST | `/api/v1/knowledge-sources` | Create Legal Source |
| GET | `/api/v1/knowledge-sources/{source_id}` | Retrieve Legal Source |
| DELETE | `/api/v1/knowledge-sources/{source_id}` | Permanently delete a legal source with its editions, documents, chunks, Qdrant vectors and files (ADMIN; `?force=true` if stuck processing) |
| GET | `/api/v1/knowledge-sources/{source_id}/documents` | Retrieve Source Documents |
| POST | `/api/v1/knowledge-sources/{source_id}/versions` | Upload a new edition (e.g. an amended Act). It is processed in the |
| GET | `/api/v1/knowledge-sources/{source_id}/versions` | Full edition history of a source, newest first. Nothing is ever deleted. |
| POST | `/api/v1/knowledge-sources/{source_id}/versions/{version_id}/activate` | Make this edition the searchable one, e.g. to ROLL BACK to an older |
| POST | `/api/v1/knowledge-sources/{source_id}/versions/{version_id}/withdraw` | Remove an edition from search (e.g. published in error). Nothing is deleted. |

### Research

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/api/v1/research/search` | Search |

### Admin: ingestion monitoring

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/v1/admin/ingestion-jobs` | List Ingestion Jobs |
| POST | `/api/v1/admin/ingestion-jobs` | Start (or retry after a failure) the full pipeline for one document. |
| GET | `/api/v1/admin/ingestion-jobs/summary` | Ingestion Summary |
| GET | `/api/v1/admin/documents/{document_id}/status` | Document Status |
| GET | `/api/v1/admin/audit-events` | List Audit Events |

### Health

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/v1/health/live` | Live |
| GET | `/api/v1/health/ready` | Ready |
| GET | `/api/v1/health/llm` | Llm |

### Assistant

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/v1/assistant/agents` | List Agents |
| POST | `/api/v1/assistant/chat` | Chat |
| POST | `/api/v1/assistant/feedback` | Rate an assistant answer (SCRUM-29). Only answers in your own conversations. |

### Drafts

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/api/v1/drafts/generate` | Generate Draft |
| GET | `/api/v1/drafts/` | List Drafts |
| GET | `/api/v1/drafts/{draft_id}` | Get Draft |
| PUT | `/api/v1/drafts/{draft_id}` | Update Draft |
| GET | `/api/v1/drafts/{draft_id}/versions` | List Draft Versions |
| POST | `/api/v1/drafts/{draft_id}/review` | Review Draft |
| POST | `/api/v1/drafts/{draft_id}/approve` | Approve Draft |
| POST | `/api/v1/drafts/{draft_id}/request-changes` | Request Changes |
| POST | `/api/v1/drafts/{draft_id}/export` | Export Draft |

### Matters

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/v1/matters` | List Matters |
| POST | `/api/v1/matters` | Create Matter |
| GET | `/api/v1/matters/{matter_id}/members` | List Members |
| POST | `/api/v1/matters/{matter_id}/members` | Add Member |

### Citations

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/api/v1/citations/verify` | Verify |

### Judge Support

| Method | Path | What it does |
| --- | --- | --- |
| POST | `/api/v1/judge-support/case-brief` | Case Brief |

### Admin: evaluation

| Method | Path | What it does |
| --- | --- | --- |
| GET | `/api/v1/admin/evaluation/reports` | List Reports |
| GET | `/api/v1/admin/evaluation/reports/{name}` | Get Report |
| GET | `/api/v1/admin/evaluation/runtime` | Runtime Stats |
| GET | `/api/v1/admin/feedback/summary` | Feedback Summary |
