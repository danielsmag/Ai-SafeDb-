"""API key hashing helpers."""

import hashlib
from typing import Final

_PREFIX_LEN: Final[int] = 8


def hash_api_key(raw_key: str) -> str:
    """Return the SHA-256 hex digest of a raw API key."""
    return hashlib.sha256(raw_key.encode("utf-8")).hexdigest()


def api_key_prefix(raw_key: str) -> str:
    """Return a short non-secret prefix for display and debugging."""
    return raw_key[:_PREFIX_LEN]
