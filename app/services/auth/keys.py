"""Password hashing and browser-session token helpers."""

import hashlib
import secrets
from typing import Final

import bcrypt

_SESSION_TOKEN_BYTES: Final[int] = 32


def hash_password(password: str) -> str:
    """Return a salted bcrypt hash for a password."""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, password_hash: str) -> bool:
    """Check a password against a bcrypt hash."""
    try:
        return bcrypt.checkpw(
            password.encode("utf-8"),
            password_hash.encode("utf-8"),
        )
    except ValueError:
        return False


def generate_session_token() -> str:
    """Return a cryptographically random browser-session token."""
    return secrets.token_urlsafe(_SESSION_TOKEN_BYTES)


def hash_session_token(raw_token: str) -> str:
    """Return the SHA-256 digest persisted for a session token."""
    return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
