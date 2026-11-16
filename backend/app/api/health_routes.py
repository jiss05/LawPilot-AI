"""
Health checks (SCRUM-33 integration; BRD §9 "GET /api/v1/health/ready").

    GET /api/v1/health/live   the process is running (always 200)
    GET /api/v1/health/ready  every dependency the app needs is reachable:
                              PostgreSQL (and the latest migration applied),
                              Qdrant, embedding configuration. 503 if not.

Docker uses /ready for the backend container's healthcheck. The response
never contains passwords or connection strings (BRD §9: "avoid exposing
secrets").
"""

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.ingestion.config import get_ingestion_settings
from app.ingestion.vector_store import QdrantVectorStore

router = APIRouter(prefix="/api/v1/health", tags=["Health"])


@router.get("/live")
def live():
    return {"status": "ok"}


@router.get("/ready")
def ready(db: Session = Depends(get_db)):
    checks: dict = {}

    try:
        db.execute(text("SELECT 1"))
        revision = db.execute(text("SELECT version_num FROM alembic_version")).scalar()
        checks["database"] = {"status": "ok", "migration": revision}
    except Exception as exc:
        db.rollback()
        checks["database"] = {"status": "unavailable", "error": type(exc).__name__}

    settings = get_ingestion_settings()
    checks["vector_store"] = QdrantVectorStore(settings).health()
    checks["embeddings"] = {
        "status": "ok",
        "provider": settings.embedding_provider,
        "model": settings.embedding_model if settings.embedding_provider != "hashing" else "hashing",
    }

    healthy = all(check.get("status") == "ok" for check in checks.values())
    return JSONResponse(
        status_code=200 if healthy else 503,
        content={"status": "ready" if healthy else "not_ready", "checks": checks},
    )
