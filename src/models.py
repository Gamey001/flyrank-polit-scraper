"""Pydantic models -- the shape of a record, written down once.

Two shapes, deliberately kept apart:

* :class:`RawBook` -- what the page said. Strings, nulls, no judgement. This is
  untrusted input, so nothing here is required to be sensible.
* :class:`Book` -- what we are willing to store. Required fields, real types,
  a numeric price. A record only becomes a ``Book`` by passing validation.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

RAW_FIELDS = (
    "title",
    "product_url",
    "price_text",
    "availability_text",
    "rating_text",
    "description",
    "source_page",
    "fetched_at",
)


class RawBook(BaseModel):
    """The eight raw fields, exactly as they appeared on the page.

    ``source_page`` and ``fetched_at`` are the provenance: the receipt showing
    where and when a fact came from. They are never overwritten.
    """

    model_config = ConfigDict(extra="forbid")

    title: str | None = None
    product_url: str
    price_text: str | None = None
    availability_text: str | None = None
    rating_text: str | None = None
    description: str | None = None
    source_page: str
    fetched_at: datetime


class Book(BaseModel):
    """A validated, storable record: raw values and clean values side by side."""

    model_config = ConfigDict(extra="forbid")

    record_id: str = Field(min_length=1, description="slug derived from the canonical URL")
    product_url: str = Field(description="canonical URL -- this record's identity")

    title: str = Field(min_length=1)
    price_gbp: float = Field(gt=0, description="price_text parsed into a number")
    price_text: str = Field(min_length=1, description="the original string, kept on purpose")
    currency: str = Field(default="GBP", min_length=3, max_length=3)
    rating: int = Field(ge=1, le=5)
    rating_text: str = Field(min_length=1)
    availability_text: str = Field(min_length=1)
    in_stock: bool
    stock_count: int | None = Field(default=None, ge=0)
    description: str | None = None

    source_page: str
    fetched_at: datetime

    @field_validator("product_url", "source_page")
    @classmethod
    def _must_be_https(cls, value: str) -> str:
        if not value.startswith("https://"):
            raise ValueError("URL must be absolute and start with https://")
        return value


class InvalidRecord(BaseModel):
    """A record that failed validation, kept with the reason it failed."""

    product_url: str | None = None
    stage: str = "validate"
    reason: str
    errors: list[dict[str, object]] = Field(default_factory=list)
    raw: dict[str, object] | None = None


class FailedPage(BaseModel):
    """A page that never arrived."""

    url: str
    stage: str
    reason: str
    status_code: int | None = None
    attempts: int = 1


class RunReport(BaseModel):
    """The honest numbers at the end of a run."""

    run_id: str
    started_at: datetime
    finished_at: datetime
    duration_seconds: float
    target: str
    catalogue_pages: int
    discovered: int
    unique_urls: int
    detail_pages: int
    pages_fetched: int = Field(description="requests that really went to the network")
    cache_hits: int
    retries: int
    valid_records: int
    invalid_records: int
    failed_pages: int
    failures: list[FailedPage] = Field(default_factory=list)
    outputs: dict[str, str] = Field(default_factory=dict)
