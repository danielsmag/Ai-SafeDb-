"""In-memory web authentication store for unit tests."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

from app.connectors.models import User, WebSession
from app.services.auth.keys import (
    generate_session_token,
    hash_session_token,
    verify_password,
)
from app.services.auth.service import (
    DEV_PASSWORD,
    DEV_PASSWORD_HASH,
    DEV_USER_ID,
    DEV_USERNAME,
)


class MemoryAuthService:
    """Process-local stand-in for :class:`AuthService`."""

    def __init__(self, session_ttl_seconds: float = 86_400.0) -> None:
        self._session_ttl_seconds: float = session_ttl_seconds
        self._user: User = User(
            id=DEV_USER_ID,
            username=DEV_USERNAME,
            password_hash=DEV_PASSWORD_HASH,
            created_at=datetime.now(UTC),
        )
        self._sessions: dict[str, WebSession] = {}

    async def ensure_schema(self) -> None:
        return None

    async def authenticate(self, username: str, password: str) -> User | None:
        if (
            username != self._user.username
            or self._user.disabled_at is not None
            or not verify_password(password, self._user.password_hash)
        ):
            return None
        return self._user

    async def create_session(self, user: User) -> tuple[WebSession, str]:
        raw_token: str = generate_session_token()
        now: datetime = datetime.now(UTC)
        session: WebSession = WebSession(
            id=uuid4(),
            token_hash=hash_session_token(raw_token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=now + timedelta(seconds=self._session_ttl_seconds),
        )
        self._sessions[session.token_hash] = session
        return session, raw_token

    async def resolve_session(self, raw_token: str) -> User | None:
        token_hash: str = hash_session_token(raw_token)
        session: WebSession | None = self._sessions.get(token_hash)
        now: datetime = datetime.now(UTC)
        if session is None or session.expires_at <= now:
            return None
        self._sessions[token_hash] = session.model_copy(
            update={
                "last_seen_at": now,
                "expires_at": now + timedelta(seconds=self._session_ttl_seconds),
            }
        )
        return self._user if session.user_id == self._user.id else None

    async def revoke_session(self, raw_token: str) -> bool:
        token_hash: str = hash_session_token(raw_token)
        return self._sessions.pop(token_hash, None) is not None

    def expire_session(self, raw_token: str) -> None:
        """Test helper: force a session past its expiry."""
        token_hash: str = hash_session_token(raw_token)
        session: WebSession | None = self._sessions.get(token_hash)
        if session is None:
            raise KeyError(token_hash)
        self._sessions[token_hash] = session.model_copy(
            update={"expires_at": datetime.now(UTC) - timedelta(seconds=1)}
        )


__all__: list[str] = [
    "DEV_PASSWORD",
    "DEV_USER_ID",
    "DEV_USERNAME",
    "MemoryAuthService",
]
