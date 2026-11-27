# LawPilot AI – Database Migrations

Migrations are managed with Alembic in `backend/migrations/`. The chain is linear, with
**9 migrations and one head (`a9c4e7d2b815`)**.

| Order | Revision | Change |
| --- | --- | --- |
| 1 | `e338d84eff4e` | Initial schema |
| 2 | `b7c21a9d4f10` | Email verification and OTP storage |
| 3 | `9abede709c56` | Professional ID on users |
| 4 | `c4d8e2f1a7b3` | Link chunks and ingestion jobs to documents; pending source status |
| 5 | `d7e3a91b5c20` | Full-text search index on `document_chunks.text` |
| 6 | `e8f4b2c6d913` | Indexes on `audit_events` |
| 7 | `f3a7c91d2e60` | Draft version history, citations, review/export timestamps |
| 8 | `2280dfb3ea2c` | OTP purpose (password reset) |
| 9 | `a9c4e7d2b815` | Draft approval: `approved_by_user_id`, `approved_at`, `review_notes` (SCRUM-24) |

## Verification (27 Nov 2026)

| Check | Result |
| --- | --- |
| `alembic heads` returns exactly one head | Pass (`a9c4e7d2b815`) |
| `alembic history` is one unbroken chain from `<base>` | Pass |
| `alembic upgrade head --sql` generates the full upgrade (offline) | Pass (55 CREATE/ALTER statements) |
| `alembic downgrade a9c4e7d2b815:2280dfb3ea2c --sql` removes exactly the 3 approval columns and their foreign key | Pass |
| SQLAlchemy model `draft_documents` matches migration 9 | Pass |
| `alembic upgrade head` on the real PostgreSQL | **To do on the Docker PC** (release checklist) |

To repeat the offline checks from `backend/` (no database needed):

```bash
alembic heads
alembic history
alembic upgrade head --sql > /tmp/upgrade.sql
```

## Applying migrations

```bash
cd backend
alembic current          # what the database is on now
alembic upgrade head     # apply everything new
alembic current          # must print a9c4e7d2b815 (head)
```

With Docker, the backend container runs `alembic upgrade head` on start.
`GET /api/v1/health/ready` reports whether the database is on the latest migration.

## Rolling back one step

```bash
alembic downgrade -1     # e.g. from a9c4e7d2b815 back to 2280dfb3ea2c
```

Back up the database first (see `RELEASE.md`). Downgrading migration 9 deletes approval
information (who approved a draft and when, and reviewer notes).
