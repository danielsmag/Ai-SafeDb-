"""Tool-call history persistence against ORM-managed app tables."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol, cast
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.engine import Result
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import col, select

from app.connectors.orm_models import ApiKeyORM, ToolCallORM, UserORM
from app.core.database import Database
from app.core.logging import logger
from app.services.history.models import (
    ApiKeyFacet,
    HistoryFacets,
    ToolCallHistory,
    ToolCallHistoryPage,
    ToolCallStatus,
)


class HistoryStore(Protocol):
    """Persistence contract for gateway tool-call history."""

    async def ensure_schema(self) -> None: ...

    async def record(self, entry: ToolCallHistory) -> None: ...

    async def list_calls(
        self,
        api_key_ids: Sequence[UUID],
        *,
        limit: int,
        offset: int,
        server: str | None = None,
        session_id: UUID | None = None,
    ) -> ToolCallHistoryPage: ...

    async def list_all_calls(
        self,
        *,
        limit: int,
        offset: int,
        server: str | None = None,
        session_id: UUID | None = None,
        user_id: UUID | None = None,
        tool_names: Sequence[str] | None = None,
        statuses: Sequence[str] | None = None,
        api_key_ids: Sequence[UUID] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> ToolCallHistoryPage: ...

    async def get_call(
        self, api_key_ids: Sequence[UUID], call_id: UUID
    ) -> ToolCallHistory | None: ...

    async def get_call_admin(self, call_id: UUID) -> ToolCallHistory | None: ...

    async def list_facets(self) -> HistoryFacets: ...


class PostgresHistoryStore:
    """Store and query tool-call audit records with SQLModel."""

    def __init__(self, database: Database) -> None:
        self._database: Database = database

    async def ensure_schema(self) -> None:
        """Create missing ORM-managed app tables."""
        await self._database.create_all()
        logger.info(
            "Ensured tool-call history schema %r",
            self._database.schema_name,
        )

    async def record(self, entry: ToolCallHistory) -> None:
        """Insert one immutable audit record."""
        row: ToolCallORM = ToolCallORM(
            id=entry.id,
            session_id=entry.session_id,
            mcp_session_id=entry.mcp_session_id,
            api_key_id=entry.api_key_id,
            api_key_name=entry.api_key_name,
            server_name=entry.server_name,
            tool_name=entry.tool_name,
            original_arguments=entry.original_arguments,
            original_sql=entry.original_sql,
            executed_sql=entry.executed_sql,
            expanded_stars=entry.expanded_stars,
            dropped_columns=entry.dropped_columns,
            hashed_columns=entry.hashed_columns,
            masked_fields=entry.masked_fields,
            removed_fields=entry.removed_fields,
            call_decision=entry.call_decision,
            result_decision=entry.result_decision,
            status=entry.status,
            error=entry.error,
            duration_ms=entry.duration_ms,
            created_at=entry.created_at,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()

    async def list_calls(
        self,
        api_key_ids: Sequence[UUID],
        *,
        limit: int,
        offset: int,
        server: str | None = None,
        session_id: UUID | None = None,
    ) -> ToolCallHistoryPage:
        """Return newest records scoped to supplied API-key principals."""
        if not api_key_ids:
            return ToolCallHistoryPage(items=[], total=0)
        predicates: list[ColumnElement[bool]] = [
            col(ToolCallORM.api_key_id).in_(list(api_key_ids))
        ]
        if server is not None:
            predicates.append(col(ToolCallORM.server_name) == server)
        if session_id is not None:
            predicates.append(col(ToolCallORM.session_id) == session_id)
        async with self._database.session() as session:
            count_result: Result[Any] = await session.execute(
                select(func.count())
                .select_from(ToolCallORM)
                .where(*predicates)
            )
            total: int = int(count_result.scalar_one())
            rows_result: Result[Any] = await session.execute(
                select(ToolCallORM)
                .where(*predicates)
                .order_by(col(ToolCallORM.created_at).desc())
                .limit(limit)
                .offset(offset)
            )
            rows: list[ToolCallORM] = list(rows_result.scalars().all())
        items: list[ToolCallHistory] = [self._to_history(row) for row in rows]
        return ToolCallHistoryPage(items=items, total=total)

    async def list_all_calls(
        self,
        *,
        limit: int,
        offset: int,
        server: str | None = None,
        session_id: UUID | None = None,
        user_id: UUID | None = None,
        tool_names: Sequence[str] | None = None,
        statuses: Sequence[str] | None = None,
        api_key_ids: Sequence[UUID] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> ToolCallHistoryPage:
        """Return records for all API keys (admin only)."""
        predicates: list[ColumnElement[bool]] = []
        if server is not None:
            predicates.append(col(ToolCallORM.server_name) == server)
        if session_id is not None:
            predicates.append(col(ToolCallORM.session_id) == session_id)
        if user_id is not None:
            predicates.append(col(ApiKeyORM.user_id) == user_id)
        if tool_names:
            predicates.append(col(ToolCallORM.tool_name).in_(list(tool_names)))
        if statuses:
            predicates.append(col(ToolCallORM.status).in_(list(statuses)))
        if api_key_ids:
            predicates.append(col(ToolCallORM.api_key_id).in_(list(api_key_ids)))
        if since is not None:
            predicates.append(col(ToolCallORM.created_at) >= since)
        if until is not None:
            predicates.append(col(ToolCallORM.created_at) <= until)

        sort_columns: dict[str, Any] = {
            "created_at": col(ToolCallORM.created_at),
            "server_name": col(ToolCallORM.server_name),
            "tool_name": col(ToolCallORM.tool_name),
            "status": col(ToolCallORM.status),
            "duration_ms": col(ToolCallORM.duration_ms),
            "api_key_name": col(ToolCallORM.api_key_name),
            "username": col(UserORM.username),
        }
        sort_column: Any = sort_columns.get(
            sort_by or "created_at",
            col(ToolCallORM.created_at),
        )
        order_expression: Any = (
            sort_column.asc() if sort_order == "asc" else sort_column.desc()
        )
        async with self._database.session() as session:
            count_result: Result[Any] = await session.execute(
                select(func.count())
                .select_from(ToolCallORM)
                .join(
                    ApiKeyORM,
                    col(ApiKeyORM.id) == col(ToolCallORM.api_key_id),
                )
                .where(*predicates)
            )
            total: int = int(count_result.scalar_one())
            rows_result: Result[Any] = await session.execute(
                select(
                    ToolCallORM,
                    col(ApiKeyORM.user_id),
                    col(UserORM.username),
                )
                .join(
                    ApiKeyORM,
                    col(ApiKeyORM.id) == col(ToolCallORM.api_key_id),
                )
                .outerjoin(
                    UserORM,
                    col(UserORM.id) == col(ApiKeyORM.user_id),
                )
                .where(*predicates)
                .order_by(order_expression)
                .limit(limit)
                .offset(offset)
            )
            rows: list[tuple[ToolCallORM, UUID | None, str | None]] = cast(
                list[tuple[ToolCallORM, UUID | None, str | None]],
                list(rows_result.tuples().all()),
            )
        items: list[ToolCallHistory] = [
            self._to_history(row, user_id=row_user_id, username=username)
            for row, row_user_id, username in rows
        ]
        return ToolCallHistoryPage(items=items, total=total)

    async def get_call(
        self, api_key_ids: Sequence[UUID], call_id: UUID
    ) -> ToolCallHistory | None:
        """Return call only when owned by supplied API key."""
        if not api_key_ids:
            return None
        async with self._database.session() as session:
            result: Result[Any] = await session.execute(
                select(ToolCallORM).where(
                    col(ToolCallORM.id) == call_id,
                    col(ToolCallORM.api_key_id).in_(list(api_key_ids)),
                )
            )
            row: ToolCallORM | None = result.scalar_one_or_none()
        return self._to_history(row) if row is not None else None

    async def get_call_admin(self, call_id: UUID) -> ToolCallHistory | None:
        """Return any call by ID (admin only)."""
        async with self._database.session() as session:
            result: Result[Any] = await session.execute(
                select(
                    ToolCallORM,
                    col(ApiKeyORM.user_id),
                    col(UserORM.username),
                )
                .join(
                    ApiKeyORM,
                    col(ApiKeyORM.id) == col(ToolCallORM.api_key_id),
                )
                .outerjoin(
                    UserORM,
                    col(UserORM.id) == col(ApiKeyORM.user_id),
                )
                .where(col(ToolCallORM.id) == call_id)
            )
            row: tuple[ToolCallORM, UUID | None, str | None] | None = cast(
                tuple[ToolCallORM, UUID | None, str | None] | None,
                result.tuples().one_or_none(),
            )
        if row is None:
            return None
        return self._to_history(row[0], user_id=row[1], username=row[2])

    async def list_facets(self) -> HistoryFacets:
        """Return distinct filter values observed in recorded tool calls."""
        async with self._database.session() as session:
            servers_result: Result[Any] = await session.execute(
                select(col(ToolCallORM.server_name))
                .distinct()
                .order_by(col(ToolCallORM.server_name))
            )
            servers: list[str] = list(servers_result.scalars().all())
            tools_result: Result[Any] = await session.execute(
                select(col(ToolCallORM.tool_name))
                .distinct()
                .order_by(col(ToolCallORM.tool_name))
            )
            tools: list[str] = list(tools_result.scalars().all())
            keys_result: Result[Any] = await session.execute(
                select(
                    col(ToolCallORM.api_key_id),
                    col(ToolCallORM.api_key_name),
                )
                .distinct()
                .order_by(col(ToolCallORM.api_key_name))
            )
            keys: list[tuple[UUID, str]] = cast(
                list[tuple[UUID, str]],
                list(keys_result.tuples().all()),
            )
        return HistoryFacets(
            servers=servers,
            tools=tools,
            api_keys=[ApiKeyFacet(id=key_id, name=name) for key_id, name in keys],
        )

    @staticmethod
    def _to_history(
        row: ToolCallORM,
        *,
        user_id: UUID | None = None,
        username: str | None = None,
    ) -> ToolCallHistory:
        return ToolCallHistory(
            id=row.id,
            session_id=row.session_id,
            mcp_session_id=row.mcp_session_id,
            api_key_id=row.api_key_id,
            api_key_name=row.api_key_name,
            user_id=user_id,
            username=username,
            server_name=row.server_name,
            tool_name=row.tool_name,
            original_arguments=row.original_arguments,
            original_sql=row.original_sql,
            executed_sql=row.executed_sql,
            expanded_stars=row.expanded_stars,
            dropped_columns=row.dropped_columns,
            hashed_columns=row.hashed_columns,
            masked_fields=row.masked_fields,
            removed_fields=row.removed_fields,
            call_decision=row.call_decision,
            result_decision=row.result_decision,
            status=cast(ToolCallStatus, row.status),
            error=row.error,
            duration_ms=row.duration_ms,
            created_at=row.created_at,
        )
