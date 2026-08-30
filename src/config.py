"""Runtime configuration.

Every knob that makes the scraper *polite* lives here, and the politeness floor
(a minimum delay between real requests) is enforced by the schema itself rather
than by convention: you cannot configure this scraper to hammer a site.

Values can be overridden with ``SCRAPER_*`` environment variables or a ``.env``
file, e.g. ``SCRAPER_MIN_DELAY_SECONDS=1.5``.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_URL = "https://github.com/gamalieldashuaDataFi/flyrank-polit-scraper"

# floor for the delay between two real requests, in seconds
MIN_POLITE_DELAY_SECONDS = 0.5


class Settings(BaseSettings):
    """Configuration for a scraping run."""

    model_config = SettingsConfigDict(
        env_prefix="SCRAPER_", env_file=".env", env_file_encoding="utf-8", extra="ignore"
    )

    base_url: str = "https://books.toscrape.com/"
    start_path: str = "catalogue/page-1.html"
    max_catalogue_pages: int = Field(default=3, ge=1, le=50)

    user_agent: str = f"FlyRankInternshipA9/1.0 (+{REPO_URL})"
    request_timeout_seconds: float = Field(default=10.0, gt=0, le=120)
    min_delay_seconds: float = Field(default=MIN_POLITE_DELAY_SECONDS, ge=MIN_POLITE_DELAY_SECONDS)
    max_attempts: int = Field(default=2, ge=1, le=5)
    backoff_base_seconds: float = Field(default=1.0, gt=0)
    backoff_max_seconds: float = Field(default=8.0, gt=0)

    cache_dir: Path = Path("cache")
    output_dir: Path = Path("output")
    cache_ttl_hours: float | None = Field(default=None, description="None = cache never expires")

    log_level: str = "INFO"
    log_json: bool = False

    @field_validator("base_url")
    @classmethod
    def _require_trailing_slash(cls, value: str) -> str:
        """A base URL without a trailing slash silently loses its last segment in urljoin."""
        return value if value.endswith("/") else value + "/"

    @property
    def start_url(self) -> str:
        from urllib.parse import urljoin

        return urljoin(self.base_url, self.start_path)

    @property
    def books_path(self) -> Path:
        return self.output_dir / "books.json"

    @property
    def errors_path(self) -> Path:
        return self.output_dir / "errors.json"

    @property
    def report_path(self) -> Path:
        return self.output_dir / "run-report.json"

    @property
    def csv_path(self) -> Path:
        return self.output_dir / "books.csv"

    @property
    def runs_dir(self) -> Path:
        return self.output_dir / "runs"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Process-wide settings singleton (also a FastAPI dependency)."""
    return Settings()
