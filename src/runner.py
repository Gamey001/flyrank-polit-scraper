"""Run bookkeeping for the API.

A scrape is slow and touches a real site, so the HTTP layer never blocks on it
and never lets two runs overlap: ``POST /runs`` starts one in a worker thread
and answers ``202`` with a link to poll.
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from .config import Settings
from .models import RunReport
from .pipeline import run_pipeline

log = logging.getLogger(__name__)


class RunState(StrEnum):
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunStatus(BaseModel):
    """What the API knows about one run, before and after it finishes."""

    run_id: str
    state: RunState
    started_at: datetime
    finished_at: datetime | None = None
    pages: int
    refresh: bool = False
    inject_broken: bool = False
    error: str | None = None
    report: RunReport | None = None


class RunInProgressError(RuntimeError):
    """A run is already in flight; starting a second one would double the traffic."""

    def __init__(self, run_id: str) -> None:
        super().__init__(f"run {run_id} is still in progress")
        self.run_id = run_id


class ScrapeRunner:
    """Starts runs, keeps their status, and allows only one at a time."""

    def __init__(self, settings: Settings, history: int = 50) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._statuses: dict[str, RunStatus] = {}
        self._order: list[str] = []
        self._active: str | None = None
        self._history = history

    @property
    def active_run_id(self) -> str | None:
        with self._lock:
            return self._active

    def status(self, run_id: str) -> RunStatus | None:
        with self._lock:
            return self._statuses.get(run_id)

    def statuses(self) -> list[RunStatus]:
        with self._lock:
            return [self._statuses[r] for r in reversed(self._order)]

    def start(
        self, *, pages: int | None = None, refresh: bool = False, inject_broken: bool = False
    ) -> RunStatus:
        """Register a run and return its status immediately.

        Raises:
            RunInProgressError: another run has not finished yet.
        """
        with self._lock:
            if self._active is not None:
                raise RunInProgressError(self._active)
            run_id = uuid.uuid4().hex[:12]
            status = RunStatus(
                run_id=run_id,
                state=RunState.RUNNING,
                started_at=datetime.now(UTC),
                pages=pages or self._settings.max_catalogue_pages,
                refresh=refresh,
                inject_broken=inject_broken,
            )
            self._remember(run_id, status)
            self._active = run_id
        return status

    def execute(self, run_id: str) -> None:
        """Run the pipeline for an already-registered run. Never raises."""
        status = self.status(run_id)
        if status is None:  # pragma: no cover - defensive
            return
        from .main import BROKEN_URL_FOR_DRILL

        try:
            result = run_pipeline(
                self._settings,
                pages=status.pages,
                force_refresh=status.refresh,
                extra_urls=[BROKEN_URL_FOR_DRILL] if status.inject_broken else None,
                run_id=run_id,
            )
            self._finish(run_id, state=RunState.SUCCEEDED, report=result.report)
        except Exception as exc:  # a failed run must not take the API down
            log.exception("run.crashed", extra={"run_id": run_id})
            self._finish(run_id, state=RunState.FAILED, error=f"{type(exc).__name__}: {exc}")

    def _remember(self, run_id: str, status: RunStatus) -> None:
        self._statuses[run_id] = status
        self._order.append(run_id)
        while len(self._order) > self._history:
            self._statuses.pop(self._order.pop(0), None)

    def _finish(
        self,
        run_id: str,
        *,
        state: RunState,
        report: RunReport | None = None,
        error: str | None = None,
    ) -> None:
        with self._lock:
            status = self._statuses.get(run_id)
            if status is not None:
                self._statuses[run_id] = status.model_copy(
                    update={
                        "state": state,
                        "finished_at": datetime.now(UTC),
                        "report": report,
                        "error": error,
                    }
                )
            if self._active == run_id:
                self._active = None


class RunRequest(BaseModel):
    """Body of ``POST /runs``."""

    pages: int | None = Field(default=None, ge=1, le=50, description="catalogue pages to walk")
    refresh: bool = Field(default=False, description="ignore the cache and ask the site again")
    inject_broken: bool = Field(
        default=False, description="add one made-up URL to prove the run survives it"
    )
