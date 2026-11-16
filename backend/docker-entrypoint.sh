#!/bin/sh
# Container start-up for the LawPilot backend (SCRUM-33).
#   1. wait until PostgreSQL accepts connections
#   2. apply database migrations (alembic upgrade head)
#   3. make sure the default roles exist
#   4. start the command given by the Dockerfile CMD (uvicorn)
set -e

echo "[entrypoint] waiting for the database..."
python - <<'PY'
import os, sys, time
from sqlalchemy import create_engine, text

url = os.environ["DATABASE_URL"]
for attempt in range(60):
    try:
        with create_engine(url).connect() as connection:
            connection.execute(text("SELECT 1"))
        print("[entrypoint] database is ready")
        sys.exit(0)
    except Exception as exc:  # not up yet
        time.sleep(2)
print("[entrypoint] database did not become ready in 120 s", file=sys.stderr)
sys.exit(1)
PY

echo "[entrypoint] applying migrations..."
alembic upgrade head

echo "[entrypoint] seeding roles..."
python - <<'PY'
import app.models  # noqa: F401
from app.db.session import SessionLocal
from app.services.role_service import seed_roles

with SessionLocal() as db:
    seed_roles(db)
PY

echo "[entrypoint] starting: $*"
exec "$@"
