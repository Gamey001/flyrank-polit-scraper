"""Unit tests for the pure normalization functions."""

from __future__ import annotations

import pytest

from src.normalization import (
    NormalizationError,
    clean_description,
    parse_availability,
    parse_price,
    parse_rating,
    record_id_from_url,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("£51.77", 51.77),
        ("Â£51.77", 51.77),  # the classic mojibake, still a price
        ("£1,051.77", 1051.77),
        ("  £9.00  ", 9.0),
        ("51.77", 51.77),
    ],
)
def test_parse_price_returns_a_number(text: str, expected: float) -> None:
    assert parse_price(text) == pytest.approx(expected)


@pytest.mark.parametrize("text", [None, "", "price on request", "£"])
def test_parse_price_rejects_what_is_not_a_price(text: str | None) -> None:
    with pytest.raises(NormalizationError):
        parse_price(text)


@pytest.mark.parametrize(
    ("text", "expected"), [("One", 1), ("three", 3), ("FIVE", 5), (" Four ", 4), ("2", 2)]
)
def test_parse_rating(text: str, expected: int) -> None:
    assert parse_rating(text) == expected


@pytest.mark.parametrize("text", [None, "", "Excellent"])
def test_parse_rating_rejects_unknown_words(text: str | None) -> None:
    with pytest.raises(NormalizationError):
        parse_rating(text)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("In stock (22 available)", (True, 22)),
        ("In stock", (True, None)),
        ("Out of stock", (False, 0)),
    ],
)
def test_parse_availability(text: str, expected: tuple[bool, int | None]) -> None:
    assert parse_availability(text) == expected


def test_clean_description_drops_the_ui_marker_only() -> None:
    assert clean_description("A real description. ...more") == "A real description."
    assert clean_description("Nothing to trim.") == "Nothing to trim."
    assert clean_description(None) is None


def test_record_id_is_derived_from_the_canonical_url() -> None:
    url = "https://books.toscrape.com/catalogue/a-light-in-the-attic_1000/index.html"
    assert record_id_from_url(url) == "a-light-in-the-attic_1000"
