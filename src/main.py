"""Command-line entry point: one command runs the whole pipeline.

    python -m src.main
"""

from __future__ import annotations

import argparse
import json

from .config import get_settings
from .logging_setup import configure_logging
from .pipeline import run_pipeline

BROKEN_URL_FOR_DRILL = "https://books.toscrape.com/catalogue/this-book-does-not-exist_0/index.html"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polite-scraper", description=__doc__)
    parser.add_argument("--pages", type=int, default=None, help="catalogue pages to walk (default 3)")
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and refetch")
    parser.add_argument(
        "--inject-broken",
        action="store_true",
        help="add one made-up book URL to the list, to prove the run survives it",
    )
    parser.add_argument("--log-json", action="store_true", help="one JSON object per log line")
    parser.add_argument("--quiet", action="store_true", help="only print the summary")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(
        "WARNING" if args.quiet else settings.log_level, args.log_json or settings.log_json
    )

    result = run_pipeline(
        settings,
        pages=args.pages,
        force_refresh=args.refresh,
        extra_urls=[BROKEN_URL_FOR_DRILL] if args.inject_broken else None,
    )
    report = result.report

    if result.books and not args.quiet:
        print("--- sample record ---")
        print(json.dumps(result.books[0].model_dump(mode="json"), indent=2, ensure_ascii=False))

    print(
        f"catalogue_pages={report.catalogue_pages} discovered={report.discovered} "
        f"unique_urls={report.unique_urls} detail_pages={report.detail_pages}"
    )
    print(
        f"valid_records={report.valid_records} invalid_records={report.invalid_records} "
        f"failed_pages={report.failed_pages}"
    )
    print(
        f"pages_fetched={report.pages_fetched} cache_hits={report.cache_hits} "
        f"duration_seconds={report.duration_seconds}"
    )
    print(f"books -> {settings.books_path} | report -> {settings.report_path}")
    # a run that fetched nothing at all is the only non-zero exit
    return 0 if report.valid_records else 1


if __name__ == "__main__":
    raise SystemExit(main())
