"""Stage 3 -- turn one book page into the eight raw fields.

Selectors are aimed at the *product area* of the page, not at the whole
document: "the first thing that looks like a price" works today and betrays you
the day the page grows a second price.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime

from bs4 import BeautifulSoup, Tag

from .discovery import parse_html
from .models import RawBook

log = logging.getLogger(__name__)

PRODUCT_AREA_SELECTOR = "article.product_page"
MAIN_SELECTOR = "div.product_main"
TITLE_SELECTOR = "div.product_main h1"
PRICE_SELECTOR = "div.product_main p.price_color"
AVAILABILITY_SELECTOR = "div.product_main p.instock.availability"
RATING_SELECTOR = "div.product_main p.star-rating"
DESCRIPTION_SELECTOR = "#product_description ~ p"


class ExtractionError(Exception):
    """The document is not a book page (or not a page at all)."""


def _clean(text: str | None) -> str | None:
    """Collapse the whitespace HTML is generous with; empty becomes None."""
    if text is None:
        return None
    collapsed = re.sub(r"\s+", " ", text).strip()
    return collapsed or None


def _text(root: Tag, selector: str) -> str | None:
    element = root.select_one(selector)
    return _clean(element.get_text()) if element else None


def extract_rating_text(root: Tag) -> str | None:
    """The rating is encoded in a class name: ``<p class="star-rating Three">``."""
    element = root.select_one(RATING_SELECTOR)
    if element is None:
        return None
    classes = [c for c in element.get("class", []) if c != "star-rating"]
    return classes[0] if classes else None


def extract_description(root: Tag) -> str | None:
    """Some books simply have no description. Store null -- never invent text."""
    element = root.select_one(DESCRIPTION_SELECTOR)
    return _clean(element.get_text()) if element else None


def extract_raw_record(
    html: bytes | str, product_url: str, source_page: str, fetched_at: datetime
) -> RawBook:
    """Build the eight-field raw record for one book page.

    Raises:
        ExtractionError: the document has no product area, so it is not a book
            page and guessing at its contents would be worse than failing.
    """
    soup: BeautifulSoup = parse_html(html)
    root = soup.select_one(PRODUCT_AREA_SELECTOR) or soup.select_one(MAIN_SELECTOR)
    if root is None:
        raise ExtractionError(f"no product area found at {product_url}")
    return RawBook(
        title=_text(root, TITLE_SELECTOR),
        product_url=product_url,
        price_text=_text(root, PRICE_SELECTOR),
        availability_text=_text(root, AVAILABILITY_SELECTOR),
        rating_text=extract_rating_text(root),
        description=extract_description(soup),
        source_page=source_page,
        fetched_at=fetched_at,
    )
