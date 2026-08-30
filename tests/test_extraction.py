"""Extraction against saved fixtures -- no network involved."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from src.extraction import ExtractionError, extract_raw_record
from src.models import RAW_FIELDS
from src.normalization import normalize

from .conftest import fixture_bytes

FETCHED_AT = datetime(2026, 8, 30, 10, 0, tzinfo=UTC)
URL = "https://books.example.test/catalogue/alpha_1/index.html"
SOURCE = "https://books.example.test/catalogue/page-1.html"


def _extract(name: str, url: str = URL):
    return extract_raw_record(fixture_bytes(name), url, SOURCE, FETCHED_AT)


def test_extracts_all_eight_raw_fields_and_collapses_whitespace() -> None:
    raw = _extract("book_full.html")
    assert set(raw.model_dump()) == set(RAW_FIELDS)
    assert raw.title == "Alpha the Adventurous"  # the fixture title is split across lines
    assert raw.price_text == "£1,051.77"
    assert raw.availability_text == "In stock (7 available)"
    assert raw.rating_text == "Four"
    assert raw.description == "A very spaced out description. ...more"
    assert raw.source_page == SOURCE and raw.fetched_at == FETCHED_AT


def test_a_book_without_a_description_stores_null_not_invented_text() -> None:
    raw = _extract("book_no_description.html")
    assert raw.description is None
    assert set(raw.model_dump()) == set(RAW_FIELDS)

    book = normalize(raw)
    assert book.description is None
    assert book.in_stock is False and book.stock_count == 0


def test_a_malformed_page_raises_instead_of_guessing() -> None:
    with pytest.raises(ExtractionError):
        _extract("book_malformed.html")


def test_normalized_record_keeps_raw_and_clean_side_by_side() -> None:
    book = normalize(_extract("book_full.html"))
    assert book.price_text == "£1,051.77" and book.price_gbp == 1051.77
    assert book.rating_text == "Four" and book.rating == 4
    assert book.description == "A very spaced out description."
    assert book.record_id == "alpha_1"
