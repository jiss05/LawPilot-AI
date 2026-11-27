"""
Admin evaluation dashboard API (SCRUM-29: "Evaluation metrics and feedback
are accessible", "Administrative access restrictions are enforced").

    GET /api/v1/admin/evaluation/reports          model evaluation reports, newest first
    GET /api/v1/admin/evaluation/reports/{name}   one report with every case
    GET /api/v1/admin/evaluation/runtime          live model-run statistics (?days=7)
    GET /api/v1/admin/feedback/summary            user ratings of assistant answers

Ingestion status, failures, source versions and indexing are served by the
existing admin ingestion and knowledge-source APIs (SCRUM-18).

Every endpoint requires the ADMIN role. Reports are the JSON files written by
scripts/evaluate_model.py to storage/evaluations/.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.dependencies import require_roles
from app.db.session import get_db
from app.models.feedback import Feedback
from app.models.model_run import ModelRun
from app.models.user import User
from app.schemas.evaluation import (
    EvaluationReport,
    EvaluationReportSummary,
    FeedbackItem,
    FeedbackSummary,
    RuntimeStats,
)

router = APIRouter(prefix="/api/v1/admin", tags=["Admin: evaluation"])

REPORTS_DIR = Path(__file__).resolve().parents[2] / "storage" / "evaluations"
_REPORT_NAME = re.compile(r"^[A-Za-z0-9._-]{1,200}\.json$")
_STAMP = re.compile(r"(\d{8}-\d{6})\.json$")

admin_only = require_roles("ADMIN")


def _created_at(path: Path) -> datetime:
    match = _STAMP.search(path.name)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%d-%H%M%S")
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime)


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and "metrics" in data else None


def _summary(path: Path, data: dict) -> dict:
    cases = data.get("cases") or []
    return {
        "name": path.name,
        "created_at": _created_at(path),
        "provider": data.get("provider"),
        "model": data.get("model"),
        "passed": bool(data.get("passed")),
        "metrics": data.get("metrics") or {},
        "checks": data.get("checks") or {},
        "criteria": data.get("criteria") or {},
        "cases_total": len(cases),
        "cases_passed": sum(1 for c in cases if c.get("passed")),
    }


@router.get("/evaluation/reports", response_model=list[EvaluationReportSummary])
def list_reports(_: User = Depends(admin_only)):
    if not REPORTS_DIR.is_dir():
        return []
    out = []
    for path in REPORTS_DIR.glob("*.json"):
        data = _load(path)
        if data is not None:
            out.append(_summary(path, data))
    out.sort(key=lambda r: r["created_at"], reverse=True)
    return out


@router.get("/evaluation/reports/{name}", response_model=EvaluationReport)
def get_report(name: str, _: User = Depends(admin_only)):
    if not _REPORT_NAME.match(name):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    path = (REPORTS_DIR / name).resolve()
    if path.parent != REPORTS_DIR.resolve() or not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    data = _load(path)
    if data is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Report not found.")
    return {**_summary(path, data), "cases": data.get("cases") or []}


def _p95(values: list[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(round(0.95 * (len(ordered) - 1))))]


@router.get("/evaluation/runtime", response_model=RuntimeStats)
def runtime_stats(
    days: int = Query(default=7, ge=1, le=90),
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    since = datetime.now(timezone.utc) - timedelta(days=days)
    rows = db.execute(
        select(ModelRun.status, ModelRun.error_code, ModelRun.prompt_version, ModelRun.duration_ms)
        .where(ModelRun.created_at >= since)
    ).all()
    durations = [r.duration_ms for r in rows if r.duration_ms is not None]
    return RuntimeStats(
        days=days,
        total_runs=len(rows),
        by_status=dict(Counter(r.status for r in rows)),
        errors_by_code=dict(Counter(r.error_code for r in rows if r.error_code)),
        by_prompt_version=dict(Counter(r.prompt_version for r in rows)),
        avg_duration_ms=int(sum(durations) / len(durations)) if durations else None,
        p95_duration_ms=_p95(durations),
    )


@router.get("/feedback/summary", response_model=FeedbackSummary)
def feedback_summary(
    _: User = Depends(admin_only),
    db: Session = Depends(get_db),
):
    rows = db.scalars(select(Feedback).order_by(Feedback.created_at.desc())).all()
    ratings = [r.rating for r in rows]
    return FeedbackSummary(
        total=len(rows),
        average_rating=round(sum(ratings) / len(ratings), 2) if ratings else None,
        by_rating={str(k): v for k, v in sorted(Counter(ratings).items())},
        by_issue_type=dict(Counter(r.issue_type for r in rows if r.issue_type)),
        recent=[
            FeedbackItem(rating=r.rating, issue_type=r.issue_type, comment=r.comment, created_at=r.created_at)
            for r in rows[:20]
        ],
    )
