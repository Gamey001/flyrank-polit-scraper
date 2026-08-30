"""Stage 2 -- walk the catalogue and discover book detail URLs.

A crawler finds the shelves; an extractor reads the labels. This module is the
crawler: it parses a catalogue page, turns every relative book link into an
absolute URL, and follows the catalogue's *own* "next" link. Nothing about the
page count or the book URLs is hardcoded -- the site is asked, not assumed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup

from .http_client import FetchError, PoliteFetcher

log = logging.getLogger(__name__)

BOOK_LINK_SELECTOR = "section article.product_pod h3 > a[href]"
NEXT_LINK_SELECTOR = "ul.pager li.next > a[href]"


def parse_html(body: bytes | str) -> BeautifulSoup:
    """Parse bytes with lxml, letting the parser honour the page's own charset."""
    return BeautifulSoup(body, "lxml")


def canonicalize(url: str) -> str:
    """Strip the fragment and any trailing '?' so one page has one identity."""
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


def extract_book_links(html: bytes | str, page_url: str) -> list[str]:
    """Absolute, canonical URLs of every book listed on one catalogue page."""
    soup = parse_html(html)
    links = [
        canonicalize(urljoin(page_url, anchor["href"]))
        for anchor in soup.select(BOOK_LINK_SELECTOR)
    ]
    return links


def extract_next_page(html: bytes | str, page_url: str) -> str | None:
    """The catalogue's own 'next' link, made absolute -- or None on the last page."""
    soup = parse_html(html)
    anchor = soup.select_one(NEXT_LINK_SELECTOR)
    return canonicalize(urljoin(page_url, anchor["href"])) if anchor else None


@dataclass
class Discovery:
    """What the crawl found, plus what it had to skip."""

    catalogue_pages: list[str] = field(default_factory=list)
    book_urls: list[str] = field(default_factory=list)
    discovered: int = 0
    failed_pages: list[dict[str, object]] = field(default_factory=list)
    source_page_by_url: dict[str, str] = field(default_factory=dict)

    @property
    def unique_urls(self) -> int:
        return len(self.book_urls)


def discover_books(
    fetcher: PoliteFetcher, start_url: str, max_pages: int, *, force_refresh: bool = False
) -> Discovery:
    """Follow the catalogue from ``start_url`` for at most ``max_pages`` pages.

    Duplicate book URLs are removed while preserving discovery order, so a book
    listed on two pages still counts once.
    """
    result = Discovery()
    seen: set[str] = set()
    next_url: str | None = canonicalize(start_url)

    while next_url and len(result.catalogue_pages) < max_pages:
        page_url = next_url
        try:
            page = fetcher.fetch(page_url, force_refresh=force_refresh)
        except FetchError as exc:
            # a missing catalogue page ends the walk, not the run
            log.error("discovery.page_failed", extra={"url": page_url, "reason": exc.reason})
            result.failed_pages.append(
                {"url": page_url, "stage": "discovery", "reason": exc.reason,
                 "status_code": exc.status_code}
            )
            break

        result.catalogue_pages.append(page_url)
        links = extract_book_links(page.body, page_url)
        result.discovered += len(links)
        for link in links:
            if link not in seen:
                seen.add(link)
                result.book_urls.append(link)
                result.source_page_by_url[link] = page_url

        log.info(
            "discovery.page",
            extra={
                "url": page_url,
                "links": len(links),
                "unique_so_far": len(result.book_urls),
                "from_cache": page.from_cache,
            },
        )
        next_url = extract_next_page(page.body, page_url)

    return result
