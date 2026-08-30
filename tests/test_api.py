"""HTTP contract of the FastAPI layer."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src import api as api_module
from src.http_client import PoliteFetcher
from src.pipeline import run_pipeline
from src.repository import BookRepository
from src.runner import ScrapeRunner

from .conftest import FakeSession


@pytest.fixture
def client(settings, catalogue_routes, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """An app wired to the fixture sandbox, with one run already stored."""
    fetcher = PoliteFetcher(settings, session=FakeSession(dict(catalogue_routes)))
    run_pipeline(settings, fetcher=fetcher)

    def fake_run_pipeline(_settings, **kwargs):
        kwargs.pop("fetcher", None)
        return run_pipeline(
            settings,
            fetcher=PoliteFetcher(settings, session=FakeSession(dict(catalogue_routes))),
            **kwargs,
        )

    monkeypatch.setattr("src.runner.run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(api_module, "get_settings", lambda: settings)
    with TestClient(api_module.app) as client:
        client.app.state.settings = settings
        client.app.state.repository = BookRepository(settings)
        client.app.state.runner = ScrapeRunner(settings)
        yield client


def test_health_reports_what_the_instance_is_pointed_at(client: TestClient) -> None:
    body = client.get("/health").json()
    assert body["status"] == "ok"
    assert body["books_available"] == 2
    assert body["active_run_id"] is None


def test_books_are_served_filtered_and_paginated(client: TestClient) -> None:
    everything = client.get("/books").json()
    assert everything["total"] == 2 and len(everything["items"]) == 2

    one = client.get("/books", params={"limit": 1, "offset": 1, "sort": "price_gbp"}).json()
    assert one["total"] == 2 and len(one["items"]) == 1
    assert one["items"][0]["record_id"] == "alpha_1"  # the pricier of the two

    filtered = client.get("/books", params={"q": "beta", "in_stock": False}).json()
    assert [item["record_id"] for item in filtered["items"]] == ["beta_2"]

    assert client.get("/books", params={"min_price": 5000}).json()["total"] == 0
    assert client.get("/books", params={"rating": 99}).status_code == 422


def test_a_single_record_and_a_missing_one(client: TestClient) -> None:
    assert client.get("/books/alpha_1").json()["title"] == "Alpha the Adventurous"
    assert client.get("/books/does-not-exist").status_code == 404


def test_rejected_records_are_served_with_their_reason(client: TestClient) -> None:
    errors = client.get("/errors").json()
    assert len(errors) == 1
    assert errors[0]["product_url"].endswith("gamma_3/index.html")
    assert "price" in errors[0]["reason"]


def test_starting_a_run_returns_202_and_a_location(client: TestClient) -> None:
    response = client.post("/runs", json={"pages": 1, "inject_broken": False})
    assert response.status_code == 202
    body = response.json()
    assert response.headers["location"] == f"/runs/{body['run_id']}"

    # TestClient runs background tasks before returning, so the run is finished
    finished = client.get(f"/runs/{body['run_id']}").json()
    assert finished["state"] == "succeeded"
    assert finished["report"]["run_id"] == body["run_id"]
    assert finished["report"]["valid_records"] == 2


def test_only_one_run_at_a_time(client: TestClient) -> None:
    runner: ScrapeRunner = client.app.state.runner
    runner.start()  # registered but never executed: the slot stays taken
    conflict = client.post("/runs", json={})
    assert conflict.status_code == 409
    assert "in progress" in conflict.json()["detail"]


def test_the_latest_report_is_available_and_an_unknown_run_is_404(client: TestClient) -> None:
    latest = client.get("/runs/latest").json()
    assert latest["valid_records"] == 2 and latest["failed_pages"] == 0
    assert client.get("/runs/deadbeefdead").status_code == 404


def test_the_csv_export_is_downloadable(client: TestClient) -> None:
    response = client.get("/books.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "record_id,title,price_gbp" in response.text
