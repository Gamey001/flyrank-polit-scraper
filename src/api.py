"""FastAPI front end for the polite scraper.

The pipeline stays a plain Python library; this module only exposes it over
HTTP:

* ``POST /runs``            start a scrape (202, one at a time)
* ``GET  /runs``            run history
* ``GET  /runs/latest``     the last run report
* ``GET  /runs/{run_id}``   one run
* ``GET  /books``           the validated records, filtered and paginated
* ``GET  /books/{id}``      one record
* ``GET  /books.csv``       the flattened export
* ``GET  /errors``          records that failed validation, with the reason
* ``GET  /health``          liveness plus what this instance is pointed at

Run it with::

    uvicorn src.api:app --reload
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import BackgroundTasks, Depends, FastAPI, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import Settings, get_settings
from .logging_setup import configure_logging
from .models import Book, InvalidRecord, RunReport
from .repository import BookRepository
from .runner import RunInProgressError, RunRequest, RunStatus, ScrapeRunner

API_TITLE = "Polite Scraper API"
API_VERSION = "1.0.0"


class HealthResponse(BaseModel):
    status: Literal["ok"] = "ok"
    version: str = API_VERSION
    target: str
    books_available: int
    active_run_id: str | None = None


class BookPage(BaseModel):
    """A page of records -- total first, so a client can size its paging."""

    total: int
    limit: int
    offset: int
    items: list[Book]


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    configure_logging(settings.log_level, settings.log_json)
    app.state.settings = settings
    app.state.repository = BookRepository(settings)
    app.state.runner = ScrapeRunner(settings)
    yield


app = FastAPI(
    title=API_TITLE,
    version=API_VERSION,
    summary="Serves the books scraped from the books.toscrape.com sandbox, and runs the scraper.",
    lifespan=lifespan,
)


def get_repository(request: Request) -> BookRepository:
    return request.app.state.repository


def get_runner(request: Request) -> ScrapeRunner:
    return request.app.state.runner


def get_app_settings(request: Request) -> Settings:
    return request.app.state.settings


RepositoryDep = Annotated[BookRepository, Depends(get_repository)]
RunnerDep = Annotated[ScrapeRunner, Depends(get_runner)]
SettingsDep = Annotated[Settings, Depends(get_app_settings)]


@app.get("/health", response_model=HealthResponse, tags=["meta"])
def health(repository: RepositoryDep, runner: RunnerDep, settings: SettingsDep) -> HealthResponse:
    return HealthResponse(
        target=settings.base_url,
        books_available=len(repository.all()),
        active_run_id=runner.active_run_id,
    )


@app.post(
    "/runs",
    response_model=RunStatus,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["runs"],
    responses={409: {"description": "another run is still in progress"}},
)
def start_run(
    payload: RunRequest,
    background: BackgroundTasks,
    runner: RunnerDep,
    response: Response,
) -> RunStatus:
    """Start a scrape in the background and return immediately.

    Only one run at a time: two concurrent runs would double the traffic the
    sandbox sees, which is exactly what this project promises not to do.
    """
    try:
        run = runner.start(
            pages=payload.pages, refresh=payload.refresh, inject_broken=payload.inject_broken
        )
    except RunInProgressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"run {exc.run_id} is still in progress",
        ) from exc
    background.add_task(runner.execute, run.run_id)
    response.headers["Location"] = f"/runs/{run.run_id}"
    return run


@app.get("/runs", response_model=list[RunStatus], tags=["runs"])
def list_runs(runner: RunnerDep) -> list[RunStatus]:
    """Runs started by *this* process, newest first."""
    return runner.statuses()


@app.get("/runs/latest", response_model=RunReport, tags=["runs"])
def latest_report(repository: RepositoryDep) -> RunReport:
    """The report of the most recent completed run, whoever started it."""
    report = repository.latest_report()
    if report is None:
        raise HTTPException(status_code=404, detail="no run report yet - start a run first")
    return report


@app.get("/runs/{run_id}", response_model=RunStatus | RunReport, tags=["runs"])
def get_run(run_id: str, runner: RunnerDep, repository: RepositoryDep) -> RunStatus | RunReport:
    """Live status for a run this process started, or the archived report."""
    live = runner.status(run_id)
    if live is not None:
        return live
    archived = repository.report(run_id)
    if archived is None:
        raise HTTPException(status_code=404, detail=f"unknown run {run_id}")
    return archived


@app.get("/books", response_model=BookPage, tags=["books"])
def list_books(
    repository: RepositoryDep,
    q: Annotated[str | None, Query(description="case-insensitive substring of the title")] = None,
    min_price: Annotated[float | None, Query(ge=0)] = None,
    max_price: Annotated[float | None, Query(ge=0)] = None,
    rating: Annotated[int | None, Query(ge=1, le=5)] = None,
    in_stock: bool | None = None,
    sort: Literal["title", "price_gbp", "rating", "record_id"] = "record_id",
    desc: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> BookPage:
    """The validated records from the last run, filtered, sorted and paginated."""
    books = repository.all()
    if q:
        needle = q.casefold()
        books = [b for b in books if needle in b.title.casefold()]
    if min_price is not None:
        books = [b for b in books if b.price_gbp >= min_price]
    if max_price is not None:
        books = [b for b in books if b.price_gbp <= max_price]
    if rating is not None:
        books = [b for b in books if b.rating == rating]
    if in_stock is not None:
        books = [b for b in books if b.in_stock is in_stock]
    books.sort(key=lambda b: getattr(b, sort), reverse=desc)
    return BookPage(total=len(books), limit=limit, offset=offset, items=books[offset : offset + limit])


@app.get("/books.csv", tags=["books"], response_class=FileResponse)
def books_csv(settings: SettingsDep) -> FileResponse:
    """The flattened CSV export written by the last run."""
    if not settings.csv_path.is_file():
        raise HTTPException(status_code=404, detail="no export yet - start a run first")
    return FileResponse(settings.csv_path, media_type="text/csv", filename="books.csv")


@app.get("/books/{record_id}", response_model=Book, tags=["books"])
def get_book(record_id: str, repository: RepositoryDep) -> Book:
    book = repository.get(record_id)
    if book is None:
        raise HTTPException(status_code=404, detail=f"unknown book {record_id}")
    return book


@app.get("/errors", response_model=list[InvalidRecord], tags=["books"])
def list_errors(repository: RepositoryDep) -> list[InvalidRecord]:
    """Records that failed validation in the last run, with the reason they failed."""
    return repository.errors()
