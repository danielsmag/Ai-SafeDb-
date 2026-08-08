"""Shared constants and helpers for gateway ORM tables."""

from datetime import UTC, datetime

APP_SCHEMA_TOKEN: str = "app"


def utc_now() -> datetime:
    return datetime.now(UTC)


__all__: list[str] = [
    "APP_SCHEMA_TOKEN",
    "utc_now",
]
