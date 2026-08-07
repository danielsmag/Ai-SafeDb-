"""In-memory web authentication store for unit tests."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.connectors.models import User, WebSession
from app.services.auth.keys import (
    generate_session_token,
    hash_password,
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
        admin_user: User = User(
            id=DEV_USER_ID,
            username=DEV_USERNAME,
            password_hash=DEV_PASSWORD_HASH,
            is_admin=True,
            created_at=datetime.now(UTC),
        )
        self._users: dict[UUID, User] = {admin_user.id: admin_user}
        self._sessions: dict[str, WebSession] = {}

    async def ensure_schema(self) -> None:
        return None

    async def authenticate(self, username: str, password: str) -> User | None:
        for user in self._users.values():
            if (
                user.username == username
                and user.disabled_at is None
                and verify_password(password, user.password_hash)
            ):
                return user
        return None

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
        user: User | None = self._users.get(session.user_id)
        if user is None or user.disabled_at is not None:
            return None
        return user

    async def revoke_session(self, raw_token: str) -> bool:
        token_hash: str = hash_session_token(raw_token)
        return self._sessions.pop(token_hash, None) is not None

    async def list_users(self) -> list[User]:
        return sorted(self._users.values(), key=lambda u: u.created_at, reverse=True)

    async def get_user(self, user_id: UUID) -> User | None:
        return self._users.get(user_id)

    async def create_user(
        self, username: str, password: str, is_admin: bool = False
    ) -> User:
        user: User = User(
            id=uuid4(),
            username=username,
            password_hash=hash_password(password),
            is_admin=is_admin,
            created_at=datetime.now(UTC),
        )
        self._users[user.id] = user
        return user

    async def update_user(
        self,
        user_id: UUID,
        *,
        password: str | None = None,
        is_admin: bool | None = None,
        disabled: bool | None = None,
    ) -> User | None:
        user: User | None = self._users.get(user_id)
        if user is None:
            return None
        updates: dict[str, object] = {}
        if password is not None:
            updates["password_hash"] = hash_password(password)
        if is_admin is not None:
            updates["is_admin"] = is_admin
        if disabled is not None:
            updates["disabled_at"] = datetime.now(UTC) if disabled else None
        if updates:
            user = user.model_copy(update=updates)
            self._users[user_id] = user
        return user

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
