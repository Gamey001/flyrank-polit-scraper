"""Shared test scaffolding.

Not a single test touches the network: a fake ``requests.Session`` serves the
HTML fixtures in ``tests/fixtures/``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.config import Settings
from src.http_client import PoliteFetcher

FIXTURES = Path(__file__).parent / "fixtures"
BASE = "https://books.example.test/"
PAGE_1 = f"{BASE}catalogue/page-1.html"
PAGE_2 = f"{BASE}catalogue/page-2.html"


def fixture_bytes(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


@dataclass
class FakeResponse:
    status_code: int
    content: bytes = b""
    headers: dict[str, str] = field(default_factory=dict)


class FakeSession:
    """A ``requests.Session`` stand-in driven by a URL -> response routing table."""

    def __init__(self, routes: dict[str, object]) -> None:
        self.routes = routes
        self.headers: dict[str, str] = {}
        self.calls: list[str] = []
        self.closed = False

    def get(self, url: str, timeout: float | None = None, allow_redirects: bool = True):
        self.calls.append(url)
        route = self.routes.get(url)
        if route is None:
            return FakeResponse(404, b"<h1>404 Not Found</h1>")
        if isinstance(route, list):  # a sequence of answers for the same URL
            route = route.pop(0) if len(route) > 1 else route[0]
        if isinstance(route, Exception):
            raise route
        return route

    def close(self) -> None:
        self.closed = True


@pytest.fixture(autouse=True)
def no_sleeping(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the politeness delay's *logic* but not its wall-clock cost."""
    monkeypatch.setattr("src.http_client.time.sleep", lambda _seconds: None)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        base_url=BASE,
        start_path="catalogue/page-1.html",
        max_catalogue_pages=3,
        cache_dir=tmp_path / "cache",
        output_dir=tmp_path / "output",
        min_delay_seconds=0.5,
        max_attempts=2,
    )


@pytest.fixture
def catalogue_routes() -> dict[str, object]:
    """A two-page catalogue holding four books, one of them listed twice."""
    return {
        PAGE_1: FakeResponse(200, fixture_bytes("catalogue_page_1.html")),
        PAGE_2: FakeResponse(200, fixture_bytes("catalogue_page_2.html")),
        f"{BASE}catalogue/alpha_1/index.html": FakeResponse(200, fixture_bytes("book_full.html")),
        f"{BASE}catalogue/beta_2/index.html": FakeResponse(
            200, fixture_bytes("book_no_description.html")
        ),
        f"{BASE}catalogue/gamma_3/index.html": FakeResponse(
            200, fixture_bytes("book_unpriced.html")
        ),
    }


@pytest.fixture
def fetcher(settings: Settings, catalogue_routes: dict[str, object]) -> PoliteFetcher:
    return PoliteFetcher(settings, session=FakeSession(catalogue_routes))
