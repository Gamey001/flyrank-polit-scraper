"""Stage 4 -- raw strings are ingredients; these functions are the prep work.

Every function here is pure: HTML in one end, a clean Python value out the
other. That is what makes them testable without a network.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from .models import Book, RawBook

_PRICE_PATTERN = re.compile(r"(\d+(?:\.\d+)?)")
_WORD_RATINGS = {"zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
# the catalogue truncates long descriptions with a literal '...more' marker
_MORE_MARKER = re.compile(r"\s*\.\.\.\s*more\s*$", re.IGNORECASE)


class NormalizationError(ValueError):
    """A raw string could not be turned into the value it is supposed to be."""


def parse_price(price_text: str | None) -> float:
    """``"£51.77"`` -> ``51.77``.

    Raises:
        NormalizationError: no number in the text.
    """
    if not price_text:
        raise NormalizationError("price_text is empty")
    candidate = price_text.replace(",", "")
    match = _PRICE_PATTERN.search(candidate)
    if not match:
        raise NormalizationError(f"no number in price_text {price_text!r}")
    return float(match.group(1))


def parse_rating(rating_text: str | None) -> int:
    """``"Three"`` -> ``3``. Also accepts a plain digit.

    Raises:
        NormalizationError: the word is not a rating.
    """
    if not rating_text:
        raise NormalizationError("rating_text is empty")
    token = rating_text.strip().lower()
    if token in _WORD_RATINGS:
        return _WORD_RATINGS[token]
    if token.isdigit():
        return int(token)
    raise NormalizationError(f"unknown rating {rating_text!r}")


def parse_availability(availability_text: str | None) -> tuple[bool, int | None]:
    """``"In stock (22 available)"`` -> ``(True, 22)``; ``"Out of stock"`` -> ``(False, 0)``."""
    if not availability_text:
        raise NormalizationError("availability_text is empty")
    text = availability_text.strip()
    in_stock = "in stock" in text.lower()
    match = re.search(r"(\d+)\s+available", text, re.IGNORECASE)
    count = int(match.group(1)) if match else (None if in_stock else 0)
    return in_stock, count


def clean_description(description: str | None) -> str | None:
    """Drop the catalogue's trailing '...more' UI marker; keep the words as written."""
    if description is None:
        return None
    cleaned = _MORE_MARKER.sub("", description).strip()
    return cleaned or None


def record_id_from_url(url: str) -> str:
    """A stable, readable id derived from the canonical URL.

    ``.../catalogue/a-light-in-the-attic_1000/index.html`` -> ``a-light-in-the-attic_1000``
    """
    segments = [segment for segment in urlsplit(url).path.split("/") if segment]
    if not segments:
        raise NormalizationError(f"no path in url {url!r}")
    if segments[-1].endswith(".html") and len(segments) > 1:
        segments = segments[:-1]
    return segments[-1].removesuffix(".html")


def normalize(raw: RawBook) -> Book:
    """Turn a raw record into a validated :class:`Book`.

    Raises:
        NormalizationError: a required raw value was missing or unparseable.
        pydantic.ValidationError: the normalized record does not fit the schema.
    """
    if not raw.title:
        raise NormalizationError("title is empty")
    in_stock, stock_count = parse_availability(raw.availability_text)
    return Book(
        record_id=record_id_from_url(raw.product_url),
        product_url=raw.product_url,
        title=raw.title,
        price_gbp=parse_price(raw.price_text),
        price_text=raw.price_text or "",
        currency="GBP",
        rating=parse_rating(raw.rating_text),
        rating_text=(raw.rating_text or "").strip(),
        availability_text=raw.availability_text or "",
        in_stock=in_stock,
        stock_count=stock_count,
        description=clean_description(raw.description),
        source_page=raw.source_page,
        fetched_at=raw.fetched_at,
    )
