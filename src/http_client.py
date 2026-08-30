"""Polite HTTP fetching with an on-disk cache.

The rules this module enforces, so no caller has to remember them:

* an honest ``User-Agent`` that names the project and links to its repo;
* a timeout on every request -- a request may never hang forever;
* the status code is checked *before* the body is treated as HTML;
* at least ``min_delay_seconds`` between two real requests (cache hits are
  free: they never leave this computer);
* one retry on a timeout / connection error / 5xx / 429, with exponential
  backoff, jitter and respect for ``Retry-After``. Never a retry on 404
  (asking again will not create the page) or 403 (the site said no).
"""

from __future__ import annotations

import email.utils
import logging
import random
import re
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from hashlib import sha1
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

from .config import Settings

log = logging.getLogger(__name__)

RETRYABLE_STATUSES = frozenset({408, 425, 429, 500, 502, 503, 504})
TERMINAL_STATUSES = frozenset({400, 401, 403, 404, 405, 410, 451})


class FetchError(Exception):
    """A page did not arrive. Carries enough context to end up in a report."""

    def __init__(
        self, url: str, reason: str, *, status_code: int | None = None, attempts: int = 1
    ) -> None:
        super().__init__(f"{url}: {reason}")
        self.url = url
        self.reason = reason
        self.status_code = status_code
        self.attempts = attempts


@dataclass(frozen=True, slots=True)
class FetchResult:
    """A page that really arrived -- from the network or from the cache."""

    url: str
    status_code: int
    body: bytes
    fetched_at: datetime
    from_cache: bool
    cache_path: Path

    @property
    def size_bytes(self) -> int:
        return len(self.body)


def cache_slug(url: str) -> str:
    """Map a URL to a readable, collision-safe cache filename.

    ``https://books.toscrape.com/catalogue/page-1.html`` -> ``catalogue-page-1.html``
    """
    parsed = urlparse(url)
    path = parsed.path.strip("/") or "index.html"
    slug = re.sub(r"[^A-Za-z0-9._-]+", "-", path.replace("/", "-")).strip("-")
    if parsed.query:  # two query strings must not collide in one filename
        slug = f"{slug}-{sha1(parsed.query.encode()).hexdigest()[:8]}"
    if not slug.endswith(".html"):
        slug = f"{slug}.html"
    return slug


class HtmlCache:
    """Bytes on disk plus a small sidecar of provenance metadata.

    The sidecar matters: on a cache hit the record must report *when the site
    was actually asked*, not when the cached copy was read back.
    """

    def __init__(self, directory: Path, ttl_hours: float | None = None) -> None:
        self.directory = Path(directory)
        self.meta_directory = self.directory / ".meta"
        self.ttl_hours = ttl_hours

    def path_for(self, url: str) -> Path:
        return self.directory / cache_slug(url)

    def _meta_path_for(self, url: str) -> Path:
        return self.meta_directory / f"{cache_slug(url)}.json"

    def load(self, url: str) -> FetchResult | None:
        body_path, meta_path = self.path_for(url), self._meta_path_for(url)
        if not (body_path.is_file() and meta_path.is_file()):
            return None
        try:
            import json

            meta: dict[str, Any] = json.loads(meta_path.read_text("utf-8"))
            fetched_at = datetime.fromisoformat(meta["fetched_at"])
        except (ValueError, KeyError, OSError):
            return None  # a corrupt entry is simply a cache miss
        if self.ttl_hours is not None and datetime.now(UTC) - fetched_at > timedelta(
            hours=self.ttl_hours
        ):
            return None
        return FetchResult(
            url=url,
            status_code=int(meta.get("status_code", 200)),
            body=body_path.read_bytes(),
            fetched_at=fetched_at,
            from_cache=True,
            cache_path=body_path,
        )

    def store(self, url: str, body: bytes, status_code: int, fetched_at: datetime) -> Path:
        import json

        body_path, meta_path = self.path_for(url), self._meta_path_for(url)
        body_path.parent.mkdir(parents=True, exist_ok=True)
        meta_path.parent.mkdir(parents=True, exist_ok=True)
        body_path.write_bytes(body)
        meta_path.write_text(
            json.dumps(
                {
                    "url": url,
                    "status_code": status_code,
                    "fetched_at": fetched_at.isoformat(),
                    "size_bytes": len(body),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        return body_path


@dataclass
class FetchStats:
    """Counters that end up in the run report."""

    network_fetches: int = 0
    cache_hits: int = 0
    retries: int = 0
    failures: int = 0

    def as_dict(self) -> dict[str, int]:
        return {
            "network_fetches": self.network_fetches,
            "cache_hits": self.cache_hits,
            "retries": self.retries,
            "failures": self.failures,
        }


class PoliteFetcher:
    """The only object in this project allowed to touch the network."""

    def __init__(
        self,
        settings: Settings,
        cache: HtmlCache | None = None,
        session: requests.Session | None = None,
    ) -> None:
        self.settings = settings
        self.cache = cache or HtmlCache(settings.cache_dir, settings.cache_ttl_hours)
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": settings.user_agent, "Accept": "text/html,application/xhtml+xml"}
        )
        self.stats = FetchStats()
        self._lock = threading.Lock()
        self._last_request_at: float | None = None

    def _wait_turn(self) -> None:
        """Sleep so that consecutive *real* requests are at least a delay apart."""
        with self._lock:
            if self._last_request_at is not None:
                elapsed = time.monotonic() - self._last_request_at
                remaining = self.settings.min_delay_seconds - elapsed
                if remaining > 0:
                    time.sleep(remaining)
            self._last_request_at = time.monotonic()

    def _backoff_seconds(self, attempt: int, retry_after: str | None) -> float:
        """Obey ``Retry-After`` when the server sends one; otherwise back off."""
        if retry_after:
            seconds = _parse_retry_after(retry_after)
            if seconds is not None:
                return min(seconds, self.settings.backoff_max_seconds)
        exponential = self.settings.backoff_base_seconds * (2 ** (attempt - 1))
        return min(exponential, self.settings.backoff_max_seconds) * random.uniform(0.8, 1.2)

    def fetch(self, url: str, *, force_refresh: bool = False) -> FetchResult:
        """Return the page for ``url``, from cache when possible.

        Raises:
            FetchError: the page did not arrive as a 200 with a body.
        """
        if not force_refresh:
            cached = self.cache.load(url)
            if cached is not None:
                self.stats.cache_hits += 1
                log.info(
                    "CACHE HIT", extra={"url": url, "size_bytes": cached.size_bytes, "status": 200}
                )
                return cached

        last_error: FetchError | None = None
        for attempt in range(1, self.settings.max_attempts + 1):
            self._wait_turn()
            try:
                response = self.session.get(
                    url, timeout=self.settings.request_timeout_seconds, allow_redirects=True
                )
            except requests.Timeout as exc:
                last_error = FetchError(
                    url, f"timeout after {self.settings.request_timeout_seconds}s", attempts=attempt
                )
                log.warning(
                    "fetch.timeout", extra={"url": url, "attempt": attempt, "error": str(exc)[:120]}
                )
            except requests.RequestException as exc:
                last_error = FetchError(
                    url, f"connection error: {type(exc).__name__}", attempts=attempt
                )
                log.warning(
                    "fetch.connection_error",
                    extra={"url": url, "attempt": attempt, "error": type(exc).__name__},
                )
            else:
                status = response.status_code
                if status == 200:
                    self.stats.network_fetches += 1
                    fetched_at = datetime.now(UTC)
                    body = response.content
                    cache_path = self.cache.store(url, body, status, fetched_at)
                    log.info(
                        "FETCH",
                        extra={
                            "url": url,
                            "status": status,
                            "size_bytes": len(body),
                            "attempt": attempt,
                        },
                    )
                    return FetchResult(url, status, body, fetched_at, False, cache_path)

                last_error = FetchError(
                    url, f"unexpected status {status}", status_code=status, attempts=attempt
                )
                if status in TERMINAL_STATUSES or status not in RETRYABLE_STATUSES:
                    log.warning(
                        "fetch.rejected", extra={"url": url, "status": status, "attempt": attempt}
                    )
                    break  # a 404/403 is an answer: never ask again
                log.warning(
                    "fetch.retryable_status",
                    extra={"url": url, "status": status, "attempt": attempt},
                )
                if attempt < self.settings.max_attempts:
                    time.sleep(self._backoff_seconds(attempt, response.headers.get("Retry-After")))
                    self.stats.retries += 1
                continue

            # only reached after an exception; the status path continues above
            if attempt < self.settings.max_attempts:
                time.sleep(self._backoff_seconds(attempt, None))
                self.stats.retries += 1

        self.stats.failures += 1
        assert last_error is not None
        log.error(
            "fetch.failed",
            extra={"url": url, "status": last_error.status_code, "reason": last_error.reason},
        )
        raise last_error

    def close(self) -> None:
        self.session.close()

    def __enter__(self) -> PoliteFetcher:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def _parse_retry_after(value: str) -> float | None:
    """``Retry-After`` is either a number of seconds or an HTTP date."""
    value = value.strip()
    if value.isdigit():
        return float(value)
    parsed = email.utils.parsedate_to_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return max(0.0, (parsed - datetime.now(UTC)).total_seconds())
