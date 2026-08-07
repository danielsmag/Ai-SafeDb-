"""Username/password authentication and browser-session persistence."""

from datetime import UTC, datetime, timedelta
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg import AsyncConnection, sql

from app.connectors.models import User, WebSession
from app.connectors.postgres import PostgresPool
from app.core.logging import logger
from app.services.auth.keys import (
    generate_session_token,
    hash_session_token,
    verify_password,
)

DEV_USER_ID: UUID = UUID("00000000-0000-4000-8000-000000000010")
DEV_USERNAME: str = "admin"
DEV_PASSWORD: str = "changeme"
DEV_PASSWORD_HASH: str = (
    "$2b$12$Wd.dqXEa0zXJr0MJtuywieBLWwJAxSlN1d5m/YUQcOTPIK5vlI.HC"
)


class AuthStore(Protocol):
    """Persistence contract for web-console authentication."""

    async def ensure_schema(self) -> None: ...

    async def authenticate(self, username: str, password: str) -> User | None: ...

    async def create_session(self, user: User) -> tuple[WebSession, str]: ...

    async def resolve_session(self, raw_token: str) -> User | None: ...

    async def revoke_session(self, raw_token: str) -> bool: ...


class AuthService:
    """Authenticate users and maintain server-side browser sessions."""

    def __init__(self, pool: PostgresPool, session_ttl_seconds: float) -> None:
        self._pool: PostgresPool = pool
        self._schema: str = pool.schema_name
        self._session_ttl_seconds: float = session_ttl_seconds

    async def ensure_schema(self) -> None:
        """Create auth tables and seed the local development user."""
        schema_id: sql.Identifier = sql.Identifier(self._schema)
        async with self._pool.connection() as conn:
            await conn.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.users (
                        id            UUID PRIMARY KEY,
                        username      TEXT NOT NULL UNIQUE,
                        password_hash TEXT NOT NULL,
                        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        disabled_at   TIMESTAMPTZ
                    )
                    """
                ).format(schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.web_sessions (
                        id           UUID PRIMARY KEY,
                        token_hash   TEXT NOT NULL UNIQUE,
                        user_id      UUID NOT NULL REFERENCES {}.users (id),
                        created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_seen_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        expires_at   TIMESTAMPTZ NOT NULL
                    )
                    """
                ).format(schema_id, schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS web_sessions_user_id_idx
                        ON {}.web_sessions (user_id)
                    """
                ).format(schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.users (id, username, password_hash)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (username) DO NOTHING
                    """
                ).format(schema_id),
                (DEV_USER_ID, DEV_USERNAME, DEV_PASSWORD_HASH),
            )
            await conn.commit()
        logger.info("Ensured web authentication schema %r", self._schema)

    async def authenticate(self, username: str, password: str) -> User | None:
        """Return an enabled user when supplied credentials are valid."""
        async with self._pool.connection() as conn:
            result: Any = await conn.execute(
                sql.SQL(
                    """
                    SELECT id, username, password_hash, created_at, disabled_at
                      FROM {}.users
                     WHERE username = %s
                       AND disabled_at IS NULL
                    """
                ).format(sql.Identifier(self._schema)),
                (username,),
            )
            row: dict[str, Any] | None = await result.fetchone()
        if row is None or not verify_password(password, row["password_hash"]):
            return None
        return self._row_to_user(row)

    async def create_session(self, user: User) -> tuple[WebSession, str]:
        """Create a browser session and return its one-time raw token."""
        raw_token: str = generate_session_token()
        now: datetime = datetime.now(UTC)
        expires_at: datetime = now + timedelta(seconds=self._session_ttl_seconds)
        session: WebSession = WebSession(
            id=uuid4(),
            token_hash=hash_session_token(raw_token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
        )
        async with self._pool.connection() as conn:
            await conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.web_sessions (
                        id, token_hash, user_id, created_at, last_seen_at, expires_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s)
                    """
                ).format(sql.Identifier(self._schema)),
                (
                    session.id,
                    session.token_hash,
                    session.user_id,
                    session.created_at,
                    session.last_seen_at,
                    session.expires_at,
                ),
            )
            await conn.commit()
        return session, raw_token

    async def resolve_session(self, raw_token: str) -> User | None:
        """Resolve and refresh a non-expired browser session."""
        token_hash: str = hash_session_token(raw_token)
        now: datetime = datetime.now(UTC)
        expires_at: datetime = now + timedelta(seconds=self._session_ttl_seconds)
        async with self._pool.connection() as conn:
            row: dict[str, Any] | None = await self._fetch_session_user(
                conn, token_hash, now
            )
            if row is None:
                return None
            await conn.execute(
                sql.SQL(
                    """
                    UPDATE {}.web_sessions
                       SET last_seen_at = %s, expires_at = %s
                     WHERE token_hash = %s
                    """
                ).format(sql.Identifier(self._schema)),
                (now, expires_at, token_hash),
            )
            await conn.commit()
        return self._row_to_user(row)

    async def revoke_session(self, raw_token: str) -> bool:
        """Delete one browser session."""
        token_hash: str = hash_session_token(raw_token)
        async with self._pool.connection() as conn:
            result: Any = await conn.execute(
                sql.SQL("DELETE FROM {}.web_sessions WHERE token_hash = %s").format(
                    sql.Identifier(self._schema)
                ),
                (token_hash,),
            )
            await conn.commit()
        return result.rowcount > 0

    async def _fetch_session_user(
        self,
        conn: AsyncConnection,
        token_hash: str,
        now: datetime,
    ) -> dict[str, Any] | None:
        result: Any = await conn.execute(
            sql.SQL(
                """
                SELECT u.id, u.username, u.password_hash, u.created_at, u.disabled_at
                  FROM {}.web_sessions AS s
                  JOIN {}.users AS u ON u.id = s.user_id
                 WHERE s.token_hash = %s
                   AND s.expires_at > %s
                   AND u.disabled_at IS NULL
                """
            ).format(
                sql.Identifier(self._schema),
                sql.Identifier(self._schema),
            ),
            (token_hash, now),
        )
        row: dict[str, Any] | None = await result.fetchone()
        return row

    @staticmethod
    def _row_to_user(row: dict[str, Any]) -> User:
        return User(
            id=row["id"],
            username=row["username"],
            password_hash=row["password_hash"],
            created_at=row["created_at"],
            disabled_at=row["disabled_at"],
        )
