"""Command-line entry point for the polite scraper."""

from __future__ import annotations

import argparse
import json

from .config import get_settings
from .discovery import discover_books
from .extraction import ExtractionError, extract_raw_record
from .http_client import FetchError, PoliteFetcher
from .logging_setup import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polite-scraper", description=__doc__)
    parser.add_argument("--pages", type=int, default=None, help="catalogue pages to walk (default 3)")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and refetch")
    parser.add_argument("--log-json", action="store_true", help="one JSON object per log line")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, args.log_json or settings.log_json)
    pages = args.pages or settings.max_catalogue_pages

    raw_records = []
    with PoliteFetcher(settings) as fetcher:
        found = discover_books(fetcher, settings.start_url, pages, force_refresh=args.refresh)
        source_of = found.source_page_by_url
        for url in found.book_urls:
            try:
                page = fetcher.fetch(url, force_refresh=args.refresh)
                raw_records.append(
                    extract_raw_record(page.body, url, source_of[url], page.fetched_at)
                )
            except (FetchError, ExtractionError) as exc:
                print(f"skipped {url}: {exc}")
        stats = fetcher.stats

    print(json.dumps(raw_records[0].model_dump(mode="json"), indent=2, ensure_ascii=False))
    print(
        f"catalogue_pages={len(found.catalogue_pages)} discovered={found.discovered} "
        f"unique_urls={found.unique_urls} detail_pages={len(raw_records)}"
    )
    print(f"cache_hits={stats.cache_hits} network_fetches={stats.network_fetches}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
