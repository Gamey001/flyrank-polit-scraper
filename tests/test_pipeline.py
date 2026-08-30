"""End-to-end pipeline behaviour, driven entirely by fixtures."""

from __future__ import annotations

import json

from src.http_client import PoliteFetcher
from src.pipeline import run_pipeline
from src.store import read_json

from .conftest import BASE, FakeSession

BROKEN = f"{BASE}catalogue/this-book-does-not-exist_0/index.html"


def _run(settings, routes, **kwargs):
    fetcher = PoliteFetcher(settings, session=FakeSession(dict(routes)))
    return run_pipeline(settings, fetcher=fetcher, **kwargs)


def test_a_clean_run_stores_only_validated_records(settings, catalogue_routes) -> None:
    result = _run(settings, catalogue_routes)

    # gamma has no parseable price, so it is rejected rather than stored
    assert [b.record_id for b in result.books] == ["alpha_1", "beta_2"]
    assert result.report.valid_records == 2
    assert result.report.invalid_records == 1
    assert result.invalid[0].product_url.endswith("gamma_3/index.html")
    assert "price" in result.invalid[0].reason

    stored = read_json(settings.books_path)
    assert len(stored) == 2
    assert all(record["product_url"].startswith("https://") for record in stored)
    assert all(isinstance(record["price_gbp"], (int, float)) for record in stored)

    errors = read_json(settings.errors_path)
    assert len(errors) == 1 and errors[0]["stage"] == "normalize"
    assert errors[0]["raw"]["price_text"] == "price on request"


def test_rerunning_produces_the_same_records_not_twice_as_many(settings, catalogue_routes) -> None:
    first = _run(settings, catalogue_routes)
    second = _run(settings, catalogue_routes)

    assert len(first.books) == len(second.books) == 2
    stored = read_json(settings.books_path)
    assert len({record["product_url"] for record in stored}) == len(stored) == 2
    assert second.report.cache_hits > 0


def test_one_broken_page_is_logged_and_skipped(settings, catalogue_routes) -> None:
    result = _run(settings, catalogue_routes, extra_urls=[BROKEN])

    assert result.report.failed_pages == 1
    assert result.report.valid_records == 2
    failure = result.report.failures[0]
    assert failure.url == BROKEN and failure.status_code == 404 and failure.stage == "fetch"


def test_the_run_report_is_written_with_honest_numbers(settings, catalogue_routes) -> None:
    result = _run(settings, catalogue_routes, extra_urls=[BROKEN])
    report = json.loads(settings.report_path.read_text("utf-8"))

    assert report["run_id"] == result.report.run_id
    assert report["catalogue_pages"] == 2
    assert report["unique_urls"] == 3
    assert report["valid_records"] == 2
    assert report["invalid_records"] == 1
    assert report["failed_pages"] == 1
    assert report["pages_fetched"] == 5  # 2 catalogue + 3 book pages; the 404 never arrived
    assert report["duration_seconds"] >= 0
    assert set(report["outputs"]) == {"books", "errors", "csv", "report"}
    assert (settings.runs_dir / f"{report['run_id']}.json").is_file()


def test_a_malformed_page_does_not_take_the_run_down(settings, catalogue_routes) -> None:
    from .conftest import FakeResponse, fixture_bytes

    routes = dict(catalogue_routes)
    routes[f"{BASE}catalogue/beta_2/index.html"] = FakeResponse(
        200, fixture_bytes("book_malformed.html")
    )
    result = _run(settings, routes)

    assert result.report.valid_records == 1
    assert [f.stage for f in result.failures] == ["extract"]


def test_the_csv_export_flattens_the_validated_records(settings, catalogue_routes) -> None:
    _run(settings, catalogue_routes)
    lines = settings.csv_path.read_text("utf-8").strip().splitlines()

    assert lines[0].startswith("record_id,title,price_gbp")
    assert len(lines) == 3  # header + two records
