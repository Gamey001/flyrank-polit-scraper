"""Crawling the catalogue: absolute URLs, no duplicates, the site sets the pace."""

from __future__ import annotations

from src.discovery import discover_books, extract_book_links, extract_next_page

from .conftest import BASE, PAGE_1, PAGE_2, fixture_bytes


def test_relative_links_become_absolute_urls() -> None:
    links = extract_book_links(fixture_bytes("catalogue_page_1.html"), PAGE_1)
    assert links[0] == f"{BASE}catalogue/alpha_1/index.html"
    assert links[1] == f"{BASE}catalogue/beta_2/index.html"  # resolved through ../catalogue/
    assert all(link.startswith("https://") for link in links)


def test_only_the_product_listing_is_harvested() -> None:
    links = extract_book_links(fixture_bytes("catalogue_page_1.html"), PAGE_1)
    assert not any("not-a-book" in link for link in links)


def test_next_link_is_followed_and_then_ends() -> None:
    assert extract_next_page(fixture_bytes("catalogue_page_1.html"), PAGE_1) == PAGE_2
    assert extract_next_page(fixture_bytes("catalogue_page_2.html"), PAGE_2) is None


def test_duplicate_book_urls_are_removed(fetcher) -> None:
    found = discover_books(fetcher, PAGE_1, max_pages=3)

    assert len(found.catalogue_pages) == 2
    assert found.discovered == 4  # alpha is listed twice
    assert found.unique_urls == 3
    assert found.book_urls == [
        f"{BASE}catalogue/alpha_1/index.html",
        f"{BASE}catalogue/beta_2/index.html",
        f"{BASE}catalogue/gamma_3/index.html",
    ]
    assert found.source_page_by_url[f"{BASE}catalogue/gamma_3/index.html"] == PAGE_2


def test_the_page_budget_is_respected(fetcher) -> None:
    found = discover_books(fetcher, PAGE_1, max_pages=1)
    assert found.catalogue_pages == [PAGE_1]
    assert found.unique_urls == 2
