"""Command-line entry point for the polite scraper."""

from __future__ import annotations

import argparse

from .config import get_settings
from .http_client import PoliteFetcher
from .logging_setup import configure_logging


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="polite-scraper", description=__doc__)
    parser.add_argument("--refresh", action="store_true", help="ignore the cache and refetch")
    parser.add_argument("--log-json", action="store_true", help="one JSON object per log line")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level, args.log_json or settings.log_json)

    with PoliteFetcher(settings) as fetcher:
        result = fetcher.fetch(settings.start_url, force_refresh=args.refresh)

    print(
        f"{'CACHE HIT' if result.from_cache else 'FETCH'} "
        f"status={result.status_code} size_bytes={result.size_bytes} "
        f"cached_at={result.cache_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
