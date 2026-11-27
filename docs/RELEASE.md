# LawPilot AI – Release Checklist and Rollback (MVP)

**Release:** MVP (Sprints 1–4) · **Branch:** `feature/llm-orchestration` → `master`

## Release checklist

Tick each item on the release PC with the Docker PC and Ollama running.

### Code and tests
- [ ] All work committed; pull request from `feature/llm-orchestration` to `master` reviewed and merged
- [ ] `cd backend && pytest` → 464 passed, 0 failed
- [ ] Integration tests with `TEST_DATABASE_URL` → all pass (24 tests)
- [ ] `cd frontend && npm run lint && npm run build` → build succeeds
- [ ] Open high-severity defects in `TEST_REPORT.md`: none

### Configuration
- [ ] `backend/.env` has a strong, unique `JWT_SECRET_KEY` (not the development one)
- [ ] Email settings work: a test registration receives its OTP
- [ ] `LLM_MODEL` pulled on the server (`ollama list`)
- [ ] `VITE_API_BASE_URL` and the CORS rule match the real frontend address (defect D9)
- [ ] `.env` files are not in git (`git status` shows none)

### Database
- [ ] Backup taken (see *Rollback*, step 1) and the file size checked
- [ ] `alembic upgrade head` run; `alembic current` prints `a9c4e7d2b815 (head)`
- [ ] `GET /api/v1/health/ready` returns ready
- [ ] At least one admin account exists (`scripts/create_admin.py`)

### Model and knowledge base
- [ ] `GET /api/v1/health/llm` reports the model available
- [ ] `python scripts/evaluate_model.py` passes (report saved in `storage/evaluations/`)
- [ ] Legal sources uploaded; **Admin → Monitoring → Ingestion** shows no failed documents
- [ ] `python scripts/smoke_test.py` passes (upload → index → search → audit)

### Walk-through in the browser
- [ ] Client: ask a question; answer shows sources with verified badges; feedback buttons work
- [ ] Client: open `/admin` by URL → sent back to `/client`
- [ ] Lawyer A: create matter, add Lawyer B as reviewer, generate a draft, submit it
- [ ] Lawyer A cannot approve own draft; Lawyer B approves; Lawyer A downloads the Word file
- [ ] Judge: prepare a brief from the example case; chronology, issues and both parties shown separately; no outcome recommended
- [ ] Admin: Monitoring shows ingestion, source versions with indexing, evaluation runs and feedback
- [ ] Stop Ollama, ask a question → "temporarily unavailable", marked not reliable; start it again

### Release
- [ ] Tag the release: `git tag -a v1.0.0-mvp -m "LawPilot MVP" && git push origin v1.0.0-mvp`
- [ ] Jira: SCRUM-24 to SCRUM-31 moved to Done; sprint closed

## Rollback procedure

Use this if the release breaks something that cannot be fixed quickly. It takes about
15 minutes.

**1. Before releasing, back up the database** (keep the file until the release is accepted):

```bash
docker exec legal-ai-postgres pg_dump -U legal_ai_user -d legal_ai -Fc > lawpilot-before-release.dump
```

Qdrant can be rebuilt from the database and the uploaded files, but a snapshot is faster:
`curl -X POST http://localhost:6333/collections/legal_chunks_v1/snapshots`.

**2. Stop the application:** close the backend and frontend windows, or `docker compose stop backend`.

**3. Go back to the previous code:**

```bash
git fetch --tags
git checkout <previous tag or commit>       # e.g. the master commit before the merge
```

**4. Put the database back on the matching migration.** Only migration 9 (`a9c4e7d2b815`) is new
in this release:

```bash
cd backend
alembic downgrade 2280dfb3ea2c
```

This removes the draft approval columns, and so who approved each draft. If the downgrade
fails, restore the backup instead:

```bash
docker exec -i legal-ai-postgres pg_restore -U legal_ai_user -d legal_ai --clean --if-exists < lawpilot-before-release.dump
```

**5. Restart and check:** start the backend and frontend, then confirm `GET /api/v1/health/ready`
says ready, an admin can sign in, and a chat question returns an answer.

**6. Record it:** note what failed and the request IDs from the error messages in a Jira bug, and
link it to the release.
