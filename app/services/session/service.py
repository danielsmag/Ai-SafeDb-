"""Session and API-key persistence against ORM-managed app tables."""

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.sql.selectable import Select
from sqlmodel import col, select

from app.connectors.models import ApiKey, ClientInfo, SessionRecord
from app.connectors.orm_models import ApiKeyORM, SessionORM
from app.core.database import Database
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
        database: Database,
        idle_ttl_seconds: float = 86_400.0,
    ) -> None:
        self._database: Database = database
        self._idle_ttl_seconds: float = idle_ttl_seconds

    async def ensure_schema(self) -> None:
        """Create app tables and seed the local development API key."""
        await self._database.create_all()
        async with self._database.session() as session:
            statement: Insert = (
                insert(ApiKeyORM)
                .values(
                    id=_DEV_KEY_ID,
                    name=_DEV_KEY_NAME,
                    key_prefix=_DEV_KEY_PREFIX,
                    key_hash=_DEV_KEY_HASH,
                    user_id=DEV_USER_ID,
                )
                .on_conflict_do_nothing(index_elements=[ApiKeyORM.key_hash])
            )
            await session.execute(statement)
            await session.execute(
                update(ApiKeyORM)
                .where(
                    col(ApiKeyORM.id) == _DEV_KEY_ID,
                    col(ApiKeyORM.user_id).is_(None),
                )
                .values(user_id=DEV_USER_ID)
            )
            await session.commit()
        logger.info("Ensured gateway schema %r", self._database.schema_name)

    async def authenticate(self, raw_key: str) -> ApiKey | None:
        """Look up non-revoked API key by hash of presented secret."""
        key_hash: str = hash_api_key(raw_key)
        async with self._database.session() as session:
            result: Result[tuple[ApiKeyORM]] = await session.execute(
                select(ApiKeyORM).where(
                    col(ApiKeyORM.key_hash) == key_hash,
                    col(ApiKeyORM.revoked_at).is_(None),
                )
            )
            row: ApiKeyORM | None = result.scalar_one_or_none()
            if row is None:
                return None
            row.last_used_at = datetime.now(UTC)
            session.add(row)
            await session.commit()
        return self._to_api_key(row)

    async def open_session(
        self,
        mcp_session_id: str,
        api_key: ApiKey,
        server_name: str,
        client_info: ClientInfo,
    ) -> SessionRecord:
        """Insert or refresh a session for the MCP transport session id."""
        session_id: UUID = uuid4()
        data_key: str = generate_session_data_key()
        now: datetime = datetime.now(UTC)
        async with self._database.session() as database_session:
            statement: Insert = (
                insert(SessionORM)
                .values(
                    id=session_id,
                    mcp_session_id=mcp_session_id,
                    api_key_id=api_key.id,
                    server_name=server_name,
                    data_key=data_key,
                    client_name=client_info.name,
                    client_version=client_info.version,
                    created_at=now,
                    last_seen_at=now,
                )
                .on_conflict_do_update(
                    index_elements=[SessionORM.mcp_session_id],
                    set_={
                        "api_key_id": api_key.id,
                        "server_name": server_name,
                        "client_name": client_info.name,
                        "client_version": client_info.version,
                        "last_seen_at": now,
                        "closed_at": None,
                    },
                )
            )
            await database_session.execute(statement)
            await database_session.commit()
            pair: tuple[SessionORM, str] | None = await self._fetch_session(
                database_session, mcp_session_id
            )
        if pair is None:
            raise RuntimeError(
                f"failed to load session after open mcp_session_id={mcp_session_id!r}"
            )
        return self._to_session(*pair)

    async def touch(self, mcp_session_id: str) -> SessionRecord | None:
        """Refresh last_seen_at for open session; return None if unknown/expired."""
        async with self._database.session() as database_session:
            pair: tuple[SessionORM, str] | None = await self._fetch_session(
                database_session, mcp_session_id
            )
            if pair is None:
                return None
            row: SessionORM = pair[0]
            key_name: str = pair[1]
            if row.closed_at is not None:
                return None
            if self._is_idle_expired(row.last_seen_at):
                row.closed_at = datetime.now(UTC)
                database_session.add(row)
                await database_session.commit()
                logger.info(
                    "Closed idle MCP session mcp_session_id=%r idle_ttl_seconds=%s",
                    mcp_session_id,
                    self._idle_ttl_seconds,
                )
                return None
            row.last_seen_at = datetime.now(UTC)
            database_session.add(row)
            await database_session.commit()
        return self._to_session(row, key_name)

    async def get_session(self, mcp_session_id: str) -> SessionRecord | None:
        """Return open, non-idle session without refreshing last_seen_at."""
        async with self._database.session() as database_session:
            pair: tuple[SessionORM, str] | None = await self._fetch_session(
                database_session, mcp_session_id
            )
            if pair is None:
                return None
            row: SessionORM = pair[0]
            key_name: str = pair[1]
            if row.closed_at is not None:
                return None
            if self._is_idle_expired(row.last_seen_at):
                row.closed_at = datetime.now(UTC)
                database_session.add(row)
                await database_session.commit()
                logger.info(
                    "Closed idle MCP session mcp_session_id=%r idle_ttl_seconds=%s",
                    mcp_session_id,
                    self._idle_ttl_seconds,
                )
                return None
        return self._to_session(row, key_name)

    async def get_latest_open_session(
        self, api_key_id: UUID
    ) -> SessionRecord | None:
        """Return most recently seen open session for an API key."""
        async with self._database.session() as database_session:
            result: Result[Any] = await database_session.execute(
                select(SessionORM, col(ApiKeyORM.name))
                .join(
                    ApiKeyORM,
                    col(ApiKeyORM.id) == col(SessionORM.api_key_id),
                )
                .where(
                    col(SessionORM.api_key_id) == api_key_id,
                    col(SessionORM.closed_at).is_(None),
                )
                .order_by(col(SessionORM.last_seen_at).desc())
                .limit(1)
            )
            pair: tuple[SessionORM, str] | None = cast(
                tuple[SessionORM, str] | None,
                result.tuples().one_or_none(),
            )
            if pair is None:
                return None
            row: SessionORM = pair[0]
            key_name: str = pair[1]
            if self._is_idle_expired(row.last_seen_at):
                row.closed_at = datetime.now(UTC)
                database_session.add(row)
                await database_session.commit()
                return None
        return self._to_session(row, key_name)

    async def list_api_key_ids_for_user(self, user_id: UUID) -> list[UUID]:
        """Return active and revoked API-key ids owned by user."""
        async with self._database.session() as session:
            result: Result[Any] = await session.execute(
                select(col(ApiKeyORM.id)).where(col(ApiKeyORM.user_id) == user_id)
            )
            ids: list[UUID] = list(result.scalars().all())
        return ids

    async def list_sessions(
        self, api_key_ids: Sequence[UUID]
    ) -> list[SessionRecord]:
        """Return sessions owned by supplied API keys, newest first."""
        if not api_key_ids:
            return []
        return await self._list_sessions_where(
            col(SessionORM.api_key_id).in_(list(api_key_ids))
        )

    async def list_all_sessions(self) -> list[SessionRecord]:
        """Return all sessions, newest first (admin only)."""
        return await self._list_sessions_where(None)

    async def close_session(self, mcp_session_id: str) -> bool:
        """Mark session closed; return whether open row changed."""
        async with self._database.session() as session:
            result: CursorResult[object] = cast(
                CursorResult[object],
                await session.execute(
                    update(SessionORM)
                    .where(
                        col(SessionORM.mcp_session_id) == mcp_session_id,
                        col(SessionORM.closed_at).is_(None),
                    )
                    .values(closed_at=datetime.now(UTC))
                )
            )
            await session.commit()
            closed: bool = result.rowcount > 0
        if closed:
            logger.info("Closed MCP session mcp_session_id=%r", mcp_session_id)
        return closed

    async def _list_sessions_where(
        self,
        predicate: ColumnElement[bool] | None,
    ) -> list[SessionRecord]:
        statement: Select[Any] = (
            select(SessionORM, col(ApiKeyORM.name))
            .join(
                ApiKeyORM,
                col(ApiKeyORM.id) == col(SessionORM.api_key_id),
            )
            .order_by(col(SessionORM.last_seen_at).desc())
        )
        if predicate is not None:
            statement = statement.where(predicate)
        async with self._database.session() as session:
            result: Result[Any] = await session.execute(statement)
            rows: list[tuple[SessionORM, str]] = cast(
                list[tuple[SessionORM, str]],
                list(result.tuples().all()),
            )
        return [self._to_session(row, key_name) for row, key_name in rows]

    @staticmethod
    async def _fetch_session(
        database_session: AsyncSession,
        mcp_session_id: str,
    ) -> tuple[SessionORM, str] | None:
        result: Result[Any] = await database_session.execute(
            select(SessionORM, col(ApiKeyORM.name))
            .join(
                ApiKeyORM,
                col(ApiKeyORM.id) == col(SessionORM.api_key_id),
            )
            .where(col(SessionORM.mcp_session_id) == mcp_session_id)
        )
        pair: tuple[SessionORM, str] | None = cast(
            tuple[SessionORM, str] | None,
            result.tuples().one_or_none(),
        )
        return pair

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

    @staticmethod
    def _to_api_key(row: ApiKeyORM) -> ApiKey:
        return ApiKey(
            id=row.id,
            name=row.name,
            key_prefix=row.key_prefix,
            key_hash=row.key_hash,
            created_at=row.created_at,
            revoked_at=row.revoked_at,
            last_used_at=row.last_used_at,
            user_id=row.user_id,
        )

    @staticmethod
    def _to_session(row: SessionORM, api_key_name: str) -> SessionRecord:
        return SessionRecord(
            id=row.id,
            mcp_session_id=row.mcp_session_id,
            api_key_id=row.api_key_id,
            api_key_name=api_key_name,
            server_name=row.server_name,
            data_key=row.data_key,
            client_name=row.client_name,
            client_version=row.client_version,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            closed_at=row.closed_at,
        )
