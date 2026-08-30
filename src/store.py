"""Writing results to disk.

Writes are atomic (temp file + ``os.replace``): a crash mid-write leaves the
previous good file in place rather than a truncated one.
"""

from __future__ import annotations

import csv
import json
import os
from collections.abc import Iterable, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel

CSV_COLUMNS = (
    "record_id",
    "title",
    "price_gbp",
    "currency",
    "rating",
    "in_stock",
    "stock_count",
    "product_url",
    "source_page",
    "fetched_at",
)


def write_json(path: Path, payload: Any) -> Path:
    """Write ``payload`` as pretty UTF-8 JSON, atomically."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)
    return path


def write_models(path: Path, models: Iterable[BaseModel]) -> Path:
    return write_json(path, [m.model_dump(mode="json") for m in models])


def write_csv(path: Path, books: Sequence[BaseModel], columns: Sequence[str] = CSV_COLUMNS) -> Path:
    """Flatten the validated records into a spreadsheet-friendly file.

    Flattened on purpose: ``description`` (long free text) and ``price_text``
    (the raw string, redundant next to ``price_gbp``) are left out.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    with temp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(columns))
        writer.writeheader()
        for book in books:
            row = book.model_dump(mode="json")
            writer.writerow({column: row.get(column) for column in columns})
    os.replace(temp, path)
    return path


def read_json(path: Path, default: Any = None) -> Any:
    if not path.is_file():
        return default
    try:
        return json.loads(path.read_text("utf-8"))
    except json.JSONDecodeError:
        return default
