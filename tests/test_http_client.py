"""The politeness rules, tested without a network."""

from __future__ import annotations

import requests

from src.http_client import FetchError, HtmlCache, PoliteFetcher, cache_slug

from .conftest import BASE, PAGE_1, FakeResponse, FakeSession


def test_cache_slug_is_readable_and_matches_the_assignment() -> None:
    assert cache_slug("https://books.toscrape.com/catalogue/page-1.html") == "catalogue-page-1.html"
    assert cache_slug("https://books.toscrape.com/") == "index.html"
    assert cache_slug("https://x.test/a/b?q=1").startswith("a-b-")


def test_second_fetch_is_served_from_cache_and_keeps_the_original_fetch_time(
    settings, catalogue_routes
) -> None:
    session = FakeSession(catalogue_routes)
    with PoliteFetcher(settings, session=session) as fetcher:
        first = fetcher.fetch(PAGE_1)
        second = fetcher.fetch(PAGE_1)

    assert session.calls == [PAGE_1]
    assert first.from_cache is False and second.from_cache is True
    assert second.fetched_at == first.fetched_at  # provenance, not read-back time
    assert second.body == first.body
    assert (settings.cache_dir / "catalogue-page-1.html").is_file()


def test_an_identifying_user_agent_and_timeout_are_always_sent(settings, catalogue_routes) -> None:
    session = FakeSession(catalogue_routes)
    fetcher = PoliteFetcher(settings, session=session)
    assert "FlyRankInternshipA9" in session.headers["User-Agent"]
    assert "http" in session.headers["User-Agent"]

    captured: dict[str, object] = {}
    original_get = session.get

    def spy(url, timeout=None, allow_redirects=True):
        captured["timeout"] = timeout
        return original_get(url, timeout=timeout, allow_redirects=allow_redirects)

    session.get = spy  # type: ignore[method-assign]
    fetcher.fetch(PAGE_1)
    assert captured["timeout"] == settings.request_timeout_seconds


def test_a_404_is_not_retried(settings) -> None:
    session = FakeSession({})  # every URL 404s
    with PoliteFetcher(settings, session=session) as fetcher:
        try:
            fetcher.fetch(f"{BASE}catalogue/nope/index.html")
        except FetchError as exc:
            assert exc.status_code == 404 and exc.attempts == 1
        else:  # pragma: no cover
            raise AssertionError("a 404 must raise FetchError")
    assert len(session.calls) == 1


def test_a_500_is_retried_once_then_succeeds(settings, catalogue_routes) -> None:
    url = PAGE_1
    routes = dict(catalogue_routes)
    routes[url] = [FakeResponse(500, b"boom"), catalogue_routes[url]]
    session = FakeSession(routes)
    with PoliteFetcher(settings, session=session) as fetcher:
        result = fetcher.fetch(url)

    assert result.status_code == 200
    assert session.calls == [url, url]
    assert fetcher.stats.retries == 1


def test_a_timeout_is_retried_then_reported(settings) -> None:
    session = FakeSession({PAGE_1: requests.Timeout("too slow")})
    with PoliteFetcher(settings, session=session) as fetcher:
        try:
            fetcher.fetch(PAGE_1)
        except FetchError as exc:
            assert "timeout" in exc.reason
        else:  # pragma: no cover
            raise AssertionError("a timeout must raise FetchError")
    assert len(session.calls) == settings.max_attempts
    assert fetcher.stats.failures == 1


def test_a_corrupt_cache_entry_is_treated_as_a_miss(settings, catalogue_routes) -> None:
    session = FakeSession(catalogue_routes)
    with PoliteFetcher(settings, session=session) as fetcher:
        fetcher.fetch(PAGE_1)
        (settings.cache_dir / ".meta" / "catalogue-page-1.html.json").write_text("{ not json")
        again = fetcher.fetch(PAGE_1)

    assert again.from_cache is False
    assert len(session.calls) == 2


def test_the_politeness_floor_cannot_be_configured_away() -> None:
    import pytest
    from pydantic import ValidationError

    from src.config import Settings

    with pytest.raises(ValidationError):
        Settings(min_delay_seconds=0.0)


def test_cache_ttl_expires_an_old_entry(settings, catalogue_routes) -> None:
    session = FakeSession(catalogue_routes)
    expiring = settings.model_copy(update={"cache_ttl_hours": 0.0})
    cache = HtmlCache(expiring.cache_dir, ttl_hours=0.0)
    with PoliteFetcher(expiring, cache=cache, session=session) as fetcher:
        fetcher.fetch(PAGE_1)
        fetcher.fetch(PAGE_1)
    assert len(session.calls) == 2
