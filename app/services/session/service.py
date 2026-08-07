"""Session and API-key persistence against the gateway Postgres schema."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol
from uuid import UUID, uuid4

from psycopg import AsyncConnection, sql

from app.connectors.models import ApiKey, ClientInfo, SessionRecord
from app.connectors.postgres import PostgresPool
from app.core.logging import logger
from app.services.auth import DEV_USER_ID
from app.services.session.keys import generate_session_data_key, hash_api_key

_DEV_KEY_ID: UUID = UUID("00000000-0000-4000-8000-000000000001")
_DEV_KEY_NAME: str = "local-dev"
_DEV_KEY_PREFIX: str = "aisk_dev"
_DEV_KEY_HASH: str = "c869076a37be0ccc37c1e36ffb64454b288ae874390783b03277f71978258183"


class SessionStore(Protocol):
    """Persistence contract used by session auth middleware."""

    async def ensure_schema(self) -> None: ...

    async def authenticate(self, raw_key: str) -> ApiKey | None: ...

    async def open_session(
        self,
        mcp_session_id: str,
        api_key: ApiKey,
        server_name: str,
        client_info: ClientInfo,
    ) -> SessionRecord: ...

    async def touch(self, mcp_session_id: str) -> SessionRecord | None: ...

    async def get_session(self, mcp_session_id: str) -> SessionRecord | None: ...

    async def get_latest_open_session(
        self, api_key_id: UUID
    ) -> SessionRecord | None: ...

    async def list_api_key_ids_for_user(self, user_id: UUID) -> list[UUID]: ...

    async def list_sessions(
        self, api_key_ids: Sequence[UUID]
    ) -> list[SessionRecord]: ...

    async def list_all_sessions(self) -> list[SessionRecord]: ...

    async def close_session(self, mcp_session_id: str) -> bool: ...


class SessionService:
    """Authenticate API keys and recognize MCP sessions in Postgres."""

    def __init__(
        self,
        pool: PostgresPool,
        idle_ttl_seconds: float = 86_400.0,
    ) -> None:
        self._pool: PostgresPool = pool
        self._schema: str = pool.schema_name
        self._idle_ttl_seconds: float = idle_ttl_seconds

    async def ensure_schema(self) -> None:
        """Create the app schema, tables, and seed the local-dev API key."""
        schema_id: sql.Identifier = sql.Identifier(self._schema)
        async with self._pool.connection() as conn:
            await conn.execute(
                sql.SQL("CREATE SCHEMA IF NOT EXISTS {}").format(schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.api_keys (
                        id            UUID PRIMARY KEY,
                        name          TEXT NOT NULL,
                        key_prefix    TEXT NOT NULL,
                        key_hash      TEXT NOT NULL UNIQUE,
                        created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        revoked_at    TIMESTAMPTZ,
                        last_used_at  TIMESTAMPTZ,
                        user_id       UUID REFERENCES {}.users (id)
                    )
                    """
                ).format(schema_id, schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    ALTER TABLE {}.api_keys
                        ADD COLUMN IF NOT EXISTS user_id UUID
                            REFERENCES {}.users (id)
                    """
                ).format(schema_id, schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.sessions (
                        id              UUID PRIMARY KEY,
                        mcp_session_id  TEXT NOT NULL UNIQUE,
                        api_key_id      UUID NOT NULL
                            REFERENCES {}.api_keys (id),
                        server_name     TEXT NOT NULL,
                        data_key        TEXT NOT NULL,
                        client_name     TEXT,
                        client_version  TEXT,
                        created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        last_seen_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                        closed_at       TIMESTAMPTZ
                    )
                    """
                ).format(schema_id, schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    ALTER TABLE {}.sessions
                        ADD COLUMN IF NOT EXISTS data_key TEXT
                    """
                ).format(schema_id)
            )
            await self._backfill_missing_data_keys(conn)
            await conn.execute(
                sql.SQL(
                    """
                    ALTER TABLE {}.sessions
                        ALTER COLUMN data_key SET NOT NULL
                    """
                ).format(schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS sessions_api_key_id_idx
                        ON {}.sessions (api_key_id)
                    """
                ).format(schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.api_keys (
                        id, name, key_prefix, key_hash, user_id
                    )
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (key_hash) DO NOTHING
                    """
                ).format(schema_id),
                (
                    _DEV_KEY_ID,
                    _DEV_KEY_NAME,
                    _DEV_KEY_PREFIX,
                    _DEV_KEY_HASH,
                    DEV_USER_ID,
                ),
            )
            await conn.execute(
                sql.SQL(
                    """
                    UPDATE {}.api_keys
                       SET user_id = %s
                     WHERE id = %s
                       AND user_id IS NULL
                    """
                ).format(schema_id),
                (DEV_USER_ID, _DEV_KEY_ID),
            )
            await conn.commit()
        logger.info("Ensured gateway schema %r", self._schema)

    async def authenticate(self, raw_key: str) -> ApiKey | None:
        """Look up a non-revoked API key by the hash of the presented secret."""
        key_hash: str = hash_api_key(raw_key)
        async with self._pool.connection() as conn:
            row: dict[str, Any] | None = await self._fetch_api_key(conn, key_hash)
            if row is None:
                return None
            api_key: ApiKey = self._row_to_api_key(row)
            await conn.execute(
                sql.SQL(
                    """
                    UPDATE {}.api_keys
                       SET last_used_at = NOW()
                     WHERE id = %s
                    """
                ).format(sql.Identifier(self._schema)),
                (api_key.id,),
            )
            await conn.commit()
            return api_key

    async def open_session(
        self,
        mcp_session_id: str,
        api_key: ApiKey,
        server_name: str,
        client_info: ClientInfo,
    ) -> SessionRecord:
        """Insert or refresh a session row for the MCP transport session id."""
        session_id: UUID = uuid4()
        data_key: str = generate_session_data_key()
        now: datetime = datetime.now(UTC)
        async with self._pool.connection() as conn:
            await conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.sessions (
                        id, mcp_session_id, api_key_id, server_name, data_key,
                        client_name, client_version, created_at, last_seen_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (mcp_session_id) DO UPDATE SET
                        api_key_id = EXCLUDED.api_key_id,
                        server_name = EXCLUDED.server_name,
                        client_name = EXCLUDED.client_name,
                        client_version = EXCLUDED.client_version,
                        last_seen_at = EXCLUDED.last_seen_at,
                        closed_at = NULL
                    """
                ).format(sql.Identifier(self._schema)),
                (
                    session_id,
                    mcp_session_id,
                    api_key.id,
                    server_name,
                    data_key,
                    client_info.name,
                    client_info.version,
                    now,
                    now,
                ),
            )
            row: dict[str, Any] | None = await self._fetch_session(conn, mcp_session_id)
            await conn.commit()
        if row is None:
            raise RuntimeError(
                f"failed to load session after open mcp_session_id={mcp_session_id!r}"
            )
        return self._row_to_session(row)

    async def touch(self, mcp_session_id: str) -> SessionRecord | None:
        """Refresh last_seen_at for an open session; return None if unknown/expired."""
        async with self._pool.connection() as conn:
            row: dict[str, Any] | None = await self._fetch_session(conn, mcp_session_id)
            if row is None or row.get("closed_at") is not None:
                await conn.commit()
                return None
            if self._is_idle_expired(row["last_seen_at"]):
                await conn.execute(
                    sql.SQL(
                        """
                        UPDATE {}.sessions
                           SET closed_at = NOW()
                         WHERE mcp_session_id = %s
                           AND closed_at IS NULL
                        """
                    ).format(sql.Identifier(self._schema)),
                    (mcp_session_id,),
                )
                await conn.commit()
                logger.info(
                    "Closed idle MCP session mcp_session_id=%r idle_ttl_seconds=%s",
                    mcp_session_id,
                    self._idle_ttl_seconds,
                )
                return None
            await conn.execute(
                sql.SQL(
                    """
                    UPDATE {}.sessions
                       SET last_seen_at = NOW()
                     WHERE mcp_session_id = %s
                       AND closed_at IS NULL
                    """
                ).format(sql.Identifier(self._schema)),
                (mcp_session_id,),
            )
            refreshed: dict[str, Any] | None = await self._fetch_session(
                conn, mcp_session_id
            )
            await conn.commit()
        if refreshed is None or refreshed.get("closed_at") is not None:
            return None
        return self._row_to_session(refreshed)

    async def get_session(self, mcp_session_id: str) -> SessionRecord | None:
        """Return an open, non-idle session without refreshing last_seen_at."""
        async with self._pool.connection() as conn:
            row: dict[str, Any] | None = await self._fetch_session(conn, mcp_session_id)
            if row is None or row.get("closed_at") is not None:
                await conn.commit()
                return None
            if self._is_idle_expired(row["last_seen_at"]):
                await conn.execute(
                    sql.SQL(
                        """
                        UPDATE {}.sessions
                           SET closed_at = NOW()
                         WHERE mcp_session_id = %s
                           AND closed_at IS NULL
                        """
                    ).format(sql.Identifier(self._schema)),
                    (mcp_session_id,),
                )
                await conn.commit()
                logger.info(
                    "Closed idle MCP session mcp_session_id=%r idle_ttl_seconds=%s",
                    mcp_session_id,
                    self._idle_ttl_seconds,
                )
                return None
            await conn.commit()
        return self._row_to_session(row)

    async def get_latest_open_session(
        self, api_key_id: UUID
    ) -> SessionRecord | None:
        """Return the most recently seen open session for an API key."""
        async with self._pool.connection() as conn:
            result: Any = await conn.execute(
                sql.SQL(
                    """
                    SELECT s.id, s.mcp_session_id, s.api_key_id, k.name AS api_key_name,
                           s.server_name, s.data_key, s.client_name, s.client_version,
                           s.created_at, s.last_seen_at, s.closed_at
                      FROM {}.sessions AS s
                      JOIN {}.api_keys AS k ON k.id = s.api_key_id
                     WHERE s.api_key_id = %s
                       AND s.closed_at IS NULL
                     ORDER BY s.last_seen_at DESC
                     LIMIT 1
                    """
                ).format(
                    sql.Identifier(self._schema),
                    sql.Identifier(self._schema),
                ),
                (api_key_id,),
            )
            row: dict[str, Any] | None = await result.fetchone()
            if row is None:
                await conn.commit()
                return None
            if self._is_idle_expired(row["last_seen_at"]):
                await conn.execute(
                    sql.SQL(
                        """
                        UPDATE {}.sessions
                           SET closed_at = NOW()
                         WHERE id = %s
                           AND closed_at IS NULL
                        """
                    ).format(sql.Identifier(self._schema)),
                    (row["id"],),
                )
                await conn.commit()
                return None
            await conn.commit()
        return self._row_to_session(row)

    async def list_api_key_ids_for_user(self, user_id: UUID) -> list[UUID]:
        """Return active and revoked API-key ids owned by a user."""
        async with self._pool.connection() as conn:
            result: Any = await conn.execute(
                sql.SQL("SELECT id FROM {}.api_keys WHERE user_id = %s").format(
                    sql.Identifier(self._schema)
                ),
                (user_id,),
            )
            rows: list[dict[str, Any]] = await result.fetchall()
        return [row["id"] for row in rows]

    async def list_sessions(
        self, api_key_ids: Sequence[UUID]
    ) -> list[SessionRecord]:
        """Return sessions owned by any supplied API key, newest first."""
        if not api_key_ids:
            return []
        async with self._pool.connection() as conn:
            result: Any = await conn.execute(
                sql.SQL(
                    """
                    SELECT s.id, s.mcp_session_id, s.api_key_id, k.name AS api_key_name,
                           s.server_name, s.data_key, s.client_name, s.client_version,
                           s.created_at, s.last_seen_at, s.closed_at
                      FROM {}.sessions AS s
                      JOIN {}.api_keys AS k ON k.id = s.api_key_id
                     WHERE s.api_key_id = ANY(%s)
                     ORDER BY s.last_seen_at DESC
                    """
                ).format(
                    sql.Identifier(self._schema),
                    sql.Identifier(self._schema),
                ),
                (list(api_key_ids),),
            )
            rows: list[dict[str, Any]] = await result.fetchall()
        return [self._row_to_session(row) for row in rows]

    async def list_all_sessions(self) -> list[SessionRecord]:
        """Return all sessions, newest first (admin only)."""
        async with self._pool.connection() as conn:
            result: Any = await conn.execute(
                sql.SQL(
                    """
                    SELECT s.id, s.mcp_session_id, s.api_key_id, k.name AS api_key_name,
                           s.server_name, s.data_key, s.client_name, s.client_version,
                           s.created_at, s.last_seen_at, s.closed_at
                      FROM {}.sessions AS s
                      JOIN {}.api_keys AS k ON k.id = s.api_key_id
                     ORDER BY s.last_seen_at DESC
                    """
                ).format(
                    sql.Identifier(self._schema),
                    sql.Identifier(self._schema),
                )
            )
            rows: list[dict[str, Any]] = await result.fetchall()
        return [self._row_to_session(row) for row in rows]

    async def close_session(self, mcp_session_id: str) -> bool:
        """Mark a session closed (client DELETE / disconnect).

        Returns True if a row was updated.
        """
        async with self._pool.connection() as conn:
            result: Any = await conn.execute(
                sql.SQL(
                    """
                    UPDATE {}.sessions
                       SET closed_at = NOW()
                     WHERE mcp_session_id = %s
                       AND closed_at IS NULL
                    """
                ).format(sql.Identifier(self._schema)),
                (mcp_session_id,),
            )
            await conn.commit()
            closed: bool = result.rowcount > 0
        if closed:
            logger.info("Closed MCP session mcp_session_id=%r", mcp_session_id)
        return closed

    def _is_idle_expired(self, last_seen_at: datetime) -> bool:
        if self._idle_ttl_seconds <= 0:
            return False
        now: datetime = datetime.now(UTC)
        seen: datetime = (
            last_seen_at
            if last_seen_at.tzinfo is not None
            else last_seen_at.replace(tzinfo=UTC)
        )
        idle_seconds: float = (now - seen).total_seconds()
        return idle_seconds > self._idle_ttl_seconds

    async def _backfill_missing_data_keys(self, conn: AsyncConnection) -> None:
        """Mint data_key for legacy session rows created before this column."""
        result: Any = await conn.execute(
            sql.SQL(
                """
                SELECT id
                  FROM {}.sessions
                 WHERE data_key IS NULL
                """
            ).format(sql.Identifier(self._schema))
        )
        rows: list[dict[str, Any]] = await result.fetchall()
        for row in rows:
            await conn.execute(
                sql.SQL(
                    """
                    UPDATE {}.sessions
                       SET data_key = %s
                     WHERE id = %s
                       AND data_key IS NULL
                    """
                ).format(sql.Identifier(self._schema)),
                (generate_session_data_key(), row["id"]),
            )

    async def _fetch_api_key(
        self, conn: AsyncConnection, key_hash: str
    ) -> dict[str, Any] | None:
        result: Any = await conn.execute(
            sql.SQL(
                """
                SELECT id, name, key_prefix, key_hash,
                       created_at, revoked_at, last_used_at, user_id
                  FROM {}.api_keys
                 WHERE key_hash = %s
                   AND revoked_at IS NULL
                """
            ).format(sql.Identifier(self._schema)),
            (key_hash,),
        )
        row: dict[str, Any] | None = await result.fetchone()
        return row

    async def _fetch_session(
        self, conn: AsyncConnection, mcp_session_id: str
    ) -> dict[str, Any] | None:
        result: Any = await conn.execute(
            sql.SQL(
                """
                SELECT s.id, s.mcp_session_id, s.api_key_id, k.name AS api_key_name,
                       s.server_name, s.data_key, s.client_name, s.client_version,
                       s.created_at, s.last_seen_at, s.closed_at
                  FROM {}.sessions AS s
                  JOIN {}.api_keys AS k ON k.id = s.api_key_id
                 WHERE s.mcp_session_id = %s
                """
            ).format(sql.Identifier(self._schema), sql.Identifier(self._schema)),
            (mcp_session_id,),
        )
        row: dict[str, Any] | None = await result.fetchone()
        return row

    @staticmethod
    def _row_to_api_key(row: dict[str, Any]) -> ApiKey:
        return ApiKey(
            id=row["id"],
            name=row["name"],
            key_prefix=row["key_prefix"],
            key_hash=row["key_hash"],
            created_at=row["created_at"],
            revoked_at=row["revoked_at"],
            last_used_at=row["last_used_at"],
            user_id=row["user_id"],
        )

    @staticmethod
    def _row_to_session(row: dict[str, Any]) -> SessionRecord:
        return SessionRecord(
            id=row["id"],
            mcp_session_id=row["mcp_session_id"],
            api_key_id=row["api_key_id"],
            api_key_name=row["api_key_name"],
            server_name=row["server_name"],
            data_key=row["data_key"],
            client_name=row["client_name"],
            client_version=row["client_version"],
            created_at=row["created_at"],
            last_seen_at=row["last_seen_at"],
            closed_at=row["closed_at"],
        )
