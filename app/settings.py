"""Backward-compatible settings import.

New code should import settings from :mod:`app.core.config`.
"""

from app.core.config import AppSettings, LogLevel

__all__: list[str] = ["AppSettings", "LogLevel"]
