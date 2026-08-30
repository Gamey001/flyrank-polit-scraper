"""The pipeline: fetch -> extract -> normalize -> validate -> store -> report.

Each book page is handled on its own, so one broken page is logged and skipped
while the other fifty-nine records survive.
"""

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import ValidationError

from .config import Settings
from .discovery import discover_books
from .extraction import ExtractionError, extract_raw_record
from .http_client import FetchError, PoliteFetcher
from .models import Book, FailedPage, InvalidRecord, RawBook, RunReport
from .normalization import NormalizationError, normalize
from .store import write_csv, write_json, write_models

log = logging.getLogger(__name__)


@dataclass
class PipelineResult:
    """Everything one run produced, in memory."""

    report: RunReport
    books: list[Book] = field(default_factory=list)
    invalid: list[InvalidRecord] = field(default_factory=list)
    failures: list[FailedPage] = field(default_factory=list)


def _validate(raw: RawBook) -> tuple[Book | None, InvalidRecord | None]:
    """Normalize and schema-check one raw record. Never raises."""
    try:
        return normalize(raw), None
    except NormalizationError as exc:
        return None, InvalidRecord(
            product_url=raw.product_url,
            stage="normalize",
            reason=str(exc),
            raw=raw.model_dump(mode="json"),
        )
    except ValidationError as exc:
        return None, InvalidRecord(
            product_url=raw.product_url,
            stage="validate",
            reason=f"{exc.error_count()} schema error(s)",
            errors=[
                {
                    "field": ".".join(str(p) for p in e["loc"]),
                    "message": e["msg"],
                    "type": e["type"],
                }
                for e in exc.errors()
            ],
            raw=raw.model_dump(mode="json"),
        )


def run_pipeline(
    settings: Settings,
    *,
    pages: int | None = None,
    force_refresh: bool = False,
    extra_urls: list[str] | None = None,
    write_outputs: bool = True,
    fetcher: PoliteFetcher | None = None,
    run_id: str | None = None,
) -> PipelineResult:
    """Run the whole pipeline once and return what it produced.

    Args:
        pages: catalogue pages to walk (defaults to the configured 3).
        force_refresh: ignore the cache and ask the site again.
        extra_urls: URLs appended to the discovered ones -- used to prove that a
            deliberately broken page is skipped rather than fatal.
        write_outputs: write books.json / errors.json / run-report.json to disk.
        run_id: reuse an id assigned by the caller (the API), so one run has one
            id everywhere it is reported.
    """
    started_at = datetime.now(UTC)
    started_monotonic = time.monotonic()
    run_id = run_id or uuid.uuid4().hex[:12]
    page_budget = pages or settings.max_catalogue_pages

    owns_fetcher = fetcher is None
    fetcher = fetcher or PoliteFetcher(settings)
    books: dict[str, Book] = {}  # canonical URL -> record, so a book counts once
    invalid: list[InvalidRecord] = []
    failures: list[FailedPage] = []

    try:
        found = discover_books(
            fetcher, settings.start_url, page_budget, force_refresh=force_refresh
        )
        failures.extend(FailedPage(**f) for f in found.failed_pages)  # type: ignore[arg-type]

        targets = list(found.book_urls)
        source_pages = dict(found.source_page_by_url)
        for extra in extra_urls or []:
            if extra not in source_pages:
                targets.append(extra)
                source_pages[extra] = settings.start_url

        for url in targets:
            try:
                page = fetcher.fetch(url, force_refresh=force_refresh)
                raw = extract_raw_record(page.body, url, source_pages[url], page.fetched_at)
            except FetchError as exc:
                failures.append(
                    FailedPage(
                        url=url,
                        stage="fetch",
                        reason=exc.reason,
                        status_code=exc.status_code,
                        attempts=exc.attempts,
                    )
                )
                continue
            except ExtractionError as exc:
                failures.append(FailedPage(url=url, stage="extract", reason=str(exc)))
                continue

            book, problem = _validate(raw)
            if book is None:
                assert problem is not None
                log.warning("record.invalid", extra={"url": url, "reason": problem.reason})
                invalid.append(problem)
                continue
            books[book.product_url] = book
    finally:
        stats = fetcher.stats
        if owns_fetcher:
            fetcher.close()

    ordered = sorted(books.values(), key=lambda b: b.record_id)
    finished_at = datetime.now(UTC)
    report = RunReport(
        run_id=run_id,
        started_at=started_at,
        finished_at=finished_at,
        duration_seconds=round(time.monotonic() - started_monotonic, 3),
        target=settings.base_url,
        catalogue_pages=len(found.catalogue_pages),
        discovered=found.discovered,
        unique_urls=found.unique_urls,
        detail_pages=len(ordered)
        + len(invalid)
        + sum(1 for f in failures if f.stage != "discovery"),
        pages_fetched=stats.network_fetches,
        cache_hits=stats.cache_hits,
        retries=stats.retries,
        valid_records=len(ordered),
        invalid_records=len(invalid),
        failed_pages=len(failures),
        failures=failures,
    )

    if write_outputs:
        report.outputs = {
            "books": str(write_models(settings.books_path, ordered)),
            "errors": str(write_models(settings.errors_path, invalid)),
            "csv": str(write_csv(settings.csv_path, ordered)),
            "report": str(settings.report_path),
        }
        write_json(settings.report_path, report.model_dump(mode="json"))
        write_json(settings.runs_dir / f"{run_id}.json", report.model_dump(mode="json"))

    log.info(
        "run.finished",
        extra={
            "run_id": run_id,
            "valid": report.valid_records,
            "invalid": report.invalid_records,
            "failed_pages": report.failed_pages,
            "cache_hits": report.cache_hits,
            "duration_seconds": report.duration_seconds,
        },
    )
    return PipelineResult(report=report, books=ordered, invalid=invalid, failures=failures)
