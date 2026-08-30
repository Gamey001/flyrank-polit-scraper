"""Read access to what a run stored.

The API never re-scrapes to answer a question: it serves the validated records
that a run already wrote. The file is re-read only when its mtime changes.
"""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import ValidationError

from .config import Settings
from .models import Book, InvalidRecord, RunReport
from .store import read_json


class BookRepository:
    """Thread-safe, mtime-cached view over ``output/books.json``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._lock = threading.Lock()
        self._books: list[Book] = []
        self._by_id: dict[str, Book] = {}
        self._stamp: tuple[float, int] | None = None

    def _stamp_of(self, path: Path) -> tuple[float, int] | None:
        try:
            stat = path.stat()
        except OSError:
            return None
        return (stat.st_mtime, stat.st_size)

    def _refresh(self) -> None:
        path = self._settings.books_path
        stamp = self._stamp_of(path)
        if stamp == self._stamp:
            return
        payload = read_json(path, default=[]) or []
        books: list[Book] = []
        for item in payload:
            try:
                books.append(Book.model_validate(item))
            except ValidationError:
                continue  # a record that no longer fits the schema is not served
        self._books = books
        self._by_id = {book.record_id: book for book in books}
        self._stamp = stamp

    def all(self) -> list[Book]:
        with self._lock:
            self._refresh()
            return list(self._books)

    def get(self, record_id: str) -> Book | None:
        with self._lock:
            self._refresh()
            return self._by_id.get(record_id)

    def errors(self) -> list[InvalidRecord]:
        payload = read_json(self._settings.errors_path, default=[]) or []
        return [InvalidRecord.model_validate(item) for item in payload]

    def latest_report(self) -> RunReport | None:
        payload = read_json(self._settings.report_path)
        return RunReport.model_validate(payload) if payload else None

    def report(self, run_id: str) -> RunReport | None:
        payload = read_json(self._settings.runs_dir / f"{run_id}.json")
        return RunReport.model_validate(payload) if payload else None

    def reports(self, limit: int = 20) -> list[RunReport]:
        directory = self._settings.runs_dir
        if not directory.is_dir():
            return []
        paths = sorted(directory.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        reports = []
        for path in paths[:limit]:
            payload = read_json(path)
            if payload:
                reports.append(RunReport.model_validate(payload))
        return reports
