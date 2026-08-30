"""Structured logging.

Log lines carry named fields (``url``, ``status``, ``attempt``, ...) so both a
human and a program can read them. ``--log-json`` switches to one JSON object
per line for machine consumption.
"""

from __future__ import annotations

import json
import logging
import sys
from typing import Any

# anything not on a bare LogRecord was passed by the caller as extra=
_STANDARD_ATTRS = set(logging.LogRecord("", 0, "", 0, "", None, None).__dict__) | {
    "asctime",
    "message",
    "taskName",
}


def _fields(record: logging.LogRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k not in _STANDARD_ATTRS}


class KeyValueFormatter(logging.Formatter):
    """``12:00:01 INFO  fetch.cache_hit url=... size_bytes=1234``"""

    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<5} {record.getMessage()}"
        extras = " ".join(f"{k}={v}" for k, v in _fields(record).items())
        line = f"{base} {extras}".rstrip()
        if record.exc_info:
            line += "\n" + self.formatException(record.exc_info)
        return line


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "event": record.getMessage(),
            **_fields(record),
        }
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(level: str = "INFO", json_logs: bool = False) -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter() if json_logs else KeyValueFormatter())
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())
    for noisy in ("urllib3", "httpx", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
