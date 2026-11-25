"""
Records every model call in the model_runs table
(SCRUM-20: "Model execution details are recorded").

One row per call: provider, model, prompt version, parameters, duration,
token counts, status and error code. Prompt and answer TEXT are never
stored here (BRD §12 "minimize logs"); answers live in `messages`, which
link back to the run through messages.model_run_id.

Recording must never break a user request: if the database is down the
failure is logged and the answer is still returned.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable, Protocol
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)


@dataclass
class RunRecord:
    provider: str
    model_name: str
    model_tag: str
    prompt_version: str
    status: str  # "succeeded" | "failed"
    duration_ms: int
    parameters: dict[str, Any] = field(default_factory=dict)
    token_metrics: dict[str, Any] = field(default_factory=dict)
    error_code: str | None = None
    id: UUID = field(default_factory=uuid4)


class RunRecorder(Protocol):
    def record(self, run: RunRecord) -> UUID | None: ...


class NullRunRecorder:
    def record(self, run: RunRecord) -> UUID | None:
        return None


class InMemoryRunRecorder:
    """Keeps runs in a list. Used by tests and the evaluation script."""

    def __init__(self) -> None:
        self.runs: list[RunRecord] = []

    def record(self, run: RunRecord) -> UUID | None:
        self.runs.append(run)
        return run.id


class DatabaseRunRecorder:
    """Writes to model_runs in its own short session, committed immediately."""

    def __init__(self, session_factory: Callable | None = None) -> None:
        self._session_factory = session_factory

    def _factory(self):
        if self._session_factory is None:
            from app.db.session import SessionLocal  # imported lazily: needs DATABASE_URL

            self._session_factory = SessionLocal
        return self._session_factory

    def record(self, run: RunRecord) -> UUID | None:
        from app.models.model_run import ModelRun

        try:
            with self._factory()() as db:
                db.add(ModelRun(
                    id=run.id,
                    provider=run.provider[:100],
                    model_name=run.model_name[:150],
                    model_tag=run.model_tag[:150],
                    prompt_version=run.prompt_version[:100],
                    parameters=run.parameters,
                    duration_ms=run.duration_ms,
                    token_metrics=run.token_metrics,
                    status=run.status,
                    error_code=run.error_code,
                ))
                db.commit()
            return run.id
        except Exception:  # never fail the user's request because logging failed
            logger.warning("Could not record model run %s", run.id, exc_info=True)
            return None
