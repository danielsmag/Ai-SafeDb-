"""Tool-call history persistence against the gateway Postgres schema."""

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from app.connectors.postgres import PostgresPool
from app.core.logging import logger
from app.services.history.models import (
    ApiKeyFacet,
    HistoryFacets,
    ToolCallHistory,
    ToolCallHistoryPage,
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
    """Store and query tool-call audit records in Postgres."""

    def __init__(self, pool: PostgresPool) -> None:
        self._pool: PostgresPool = pool
        self._schema: str = pool.schema_name

    async def ensure_schema(self) -> None:
        """Create history table and lookup indexes."""
        schema_id: sql.Identifier = sql.Identifier(self._schema)
        async with self._pool.connection() as conn:
            await conn.execute(
                sql.SQL(
                    """
                    CREATE TABLE IF NOT EXISTS {}.tool_calls (
                        id UUID PRIMARY KEY,
                        session_id UUID NOT NULL REFERENCES {}.sessions (id),
                        mcp_session_id TEXT NOT NULL,
                        api_key_id UUID NOT NULL REFERENCES {}.api_keys (id),
                        api_key_name TEXT NOT NULL,
                        server_name TEXT NOT NULL,
                        tool_name TEXT NOT NULL,
                        original_arguments JSONB NOT NULL DEFAULT '{{}}'::jsonb,
                        original_sql TEXT[] NOT NULL DEFAULT '{{}}',
                        executed_sql TEXT[] NOT NULL DEFAULT '{{}}',
                        expanded_stars BOOLEAN NOT NULL DEFAULT FALSE,
                        dropped_columns TEXT[] NOT NULL DEFAULT '{{}}',
                        hashed_columns TEXT[] NOT NULL DEFAULT '{{}}',
                        masked_fields TEXT[] NOT NULL DEFAULT '{{}}',
                        removed_fields TEXT[] NOT NULL DEFAULT '{{}}',
                        call_decision TEXT,
                        result_decision TEXT,
                        status TEXT NOT NULL
                            CHECK (status IN ('ok', 'blocked', 'error')),
                        error TEXT,
                        duration_ms DOUBLE PRECISION NOT NULL DEFAULT 0,
                        created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                    )
                    """
                ).format(schema_id, schema_id, schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS tool_calls_api_key_created_idx
                        ON {}.tool_calls (api_key_id, created_at DESC)
                    """
                ).format(schema_id)
            )
            await conn.execute(
                sql.SQL(
                    """
                    CREATE INDEX IF NOT EXISTS tool_calls_session_id_idx
                        ON {}.tool_calls (session_id)
                    """
                ).format(schema_id)
            )
            await conn.commit()
        logger.info("Ensured tool-call history schema %r", self._schema)

    async def record(self, entry: ToolCallHistory) -> None:
        """Insert one immutable audit record."""
        async with self._pool.connection() as conn:
            await conn.execute(
                sql.SQL(
                    """
                    INSERT INTO {}.tool_calls (
                        id, session_id, mcp_session_id, api_key_id, api_key_name,
                        server_name, tool_name, original_arguments, original_sql,
                        executed_sql, expanded_stars, dropped_columns,
                        hashed_columns, masked_fields, removed_fields,
                        call_decision, result_decision, status, error,
                        duration_ms, created_at
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """
                ).format(sql.Identifier(self._schema)),
                (
                    entry.id,
                    entry.session_id,
                    entry.mcp_session_id,
                    entry.api_key_id,
                    entry.api_key_name,
                    entry.server_name,
                    entry.tool_name,
                    Jsonb(entry.original_arguments),
                    entry.original_sql,
                    entry.executed_sql,
                    entry.expanded_stars,
                    entry.dropped_columns,
                    entry.hashed_columns,
                    entry.masked_fields,
                    entry.removed_fields,
                    entry.call_decision,
                    entry.result_decision,
                    entry.status,
                    entry.error,
                    entry.duration_ms,
                    entry.created_at,
                ),
            )
            await conn.commit()

    async def list_calls(
        self,
        api_key_ids: Sequence[UUID],
        *,
        limit: int,
        offset: int,
        server: str | None = None,
        session_id: UUID | None = None,
    ) -> ToolCallHistoryPage:
        """Return newest records scoped to the supplied API-key principals."""
        if not api_key_ids:
            return ToolCallHistoryPage(items=[], total=0)
        predicates: list[sql.SQL] = [sql.SQL("api_key_id = ANY(%s)")]
        params: list[object] = [list(api_key_ids)]
        if server is not None:
            predicates.append(sql.SQL("server_name = %s"))
            params.append(server)
        if session_id is not None:
            predicates.append(sql.SQL("session_id = %s"))
            params.append(session_id)
        where_clause: sql.Composed = sql.SQL(" AND ").join(predicates)
        schema_id: sql.Identifier = sql.Identifier(self._schema)
        async with self._pool.connection() as conn:
            count_result: Any = await conn.execute(
                sql.SQL("SELECT COUNT(*) AS total FROM {}.tool_calls WHERE {}").format(
                    schema_id, where_clause
                ),
                tuple(params),
            )
            count_row: dict[str, Any] = await count_result.fetchone()
            page_params: list[object] = [*params, limit, offset]
            rows_result: Any = await conn.execute(
                sql.SQL(
                    """
                    SELECT *
                      FROM {}.tool_calls
                     WHERE {}
                     ORDER BY created_at DESC
                     LIMIT %s OFFSET %s
                    """
                ).format(schema_id, where_clause),
                tuple(page_params),
            )
            rows: list[dict[str, Any]] = await rows_result.fetchall()
        items: list[ToolCallHistory] = [
            ToolCallHistory.model_validate(row) for row in rows
        ]
        return ToolCallHistoryPage(items=items, total=int(count_row["total"]))

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
        predicates: list[sql.SQL] = []
        params: list[object] = []
        if server is not None:
            predicates.append(sql.SQL("t.server_name = %s"))
            params.append(server)
        if session_id is not None:
            predicates.append(sql.SQL("t.session_id = %s"))
            params.append(session_id)
        if user_id is not None:
            predicates.append(sql.SQL("k.user_id = %s"))
            params.append(user_id)
        if tool_names:
            predicates.append(sql.SQL("t.tool_name = ANY(%s)"))
            params.append(list(tool_names))
        if statuses:
            predicates.append(sql.SQL("t.status = ANY(%s)"))
            params.append(list(statuses))
        if api_key_ids:
            predicates.append(sql.SQL("t.api_key_id = ANY(%s)"))
            params.append(list(api_key_ids))
        if since is not None:
            predicates.append(sql.SQL("t.created_at >= %s"))
            params.append(since)
        if until is not None:
            predicates.append(sql.SQL("t.created_at <= %s"))
            params.append(until)
        where_clause: sql.Composed | sql.SQL = (
            sql.SQL(" AND ").join(predicates) if predicates else sql.SQL("TRUE")
        )
        allowed_sort_columns: dict[str, str] = {
            "created_at": "t.created_at",
            "server_name": "t.server_name",
            "tool_name": "t.tool_name",
            "status": "t.status",
            "duration_ms": "t.duration_ms",
            "api_key_name": "t.api_key_name",
            "username": "u.username",
        }
        sort_col: str = allowed_sort_columns.get(
            sort_by or "created_at", "t.created_at"
        )
        order: str = "ASC" if sort_order == "asc" else "DESC"
        order_clause: sql.SQL = sql.SQL("{} {}").format(
            sql.SQL(sort_col), sql.SQL(order)
        )
        schema_id: sql.Identifier = sql.Identifier(self._schema)
        async with self._pool.connection() as conn:
            count_result: Any = await conn.execute(
                sql.SQL(
                    """
                    SELECT COUNT(*) AS total
                      FROM {}.tool_calls AS t
                      JOIN {}.api_keys AS k ON k.id = t.api_key_id
                     WHERE {}
                    """
                ).format(schema_id, schema_id, where_clause),
                tuple(params),
            )
            count_row: dict[str, Any] = await count_result.fetchone()
            page_params: list[object] = [*params, limit, offset]
            rows_result: Any = await conn.execute(
                sql.SQL(
                    """
                    SELECT t.*, k.user_id, u.username
                      FROM {}.tool_calls AS t
                      JOIN {}.api_keys AS k ON k.id = t.api_key_id
                      LEFT JOIN {}.users AS u ON u.id = k.user_id
                     WHERE {}
                     ORDER BY {}
                     LIMIT %s OFFSET %s
                    """
                ).format(
                    schema_id, schema_id, schema_id, where_clause, order_clause
                ),
                tuple(page_params),
            )
            rows: list[dict[str, Any]] = await rows_result.fetchall()
        items: list[ToolCallHistory] = [
            ToolCallHistory.model_validate(row) for row in rows
        ]
        return ToolCallHistoryPage(items=items, total=int(count_row["total"]))

    async def get_call(
        self, api_key_ids: Sequence[UUID], call_id: UUID
    ) -> ToolCallHistory | None:
        """Return a call only when owned by a supplied API key."""
        if not api_key_ids:
            return None
        async with self._pool.connection() as conn:
            result: Any = await conn.execute(
                sql.SQL(
                    """
                    SELECT *
                      FROM {}.tool_calls
                     WHERE id = %s AND api_key_id = ANY(%s)
                    """
                ).format(sql.Identifier(self._schema)),
                (call_id, list(api_key_ids)),
            )
            row: dict[str, Any] | None = await result.fetchone()
        return ToolCallHistory.model_validate(row) if row is not None else None

    async def get_call_admin(self, call_id: UUID) -> ToolCallHistory | None:
        """Return any call by ID (admin only)."""
        async with self._pool.connection() as conn:
            result: Any = await conn.execute(
                sql.SQL("SELECT * FROM {}.tool_calls WHERE id = %s").format(
                    sql.Identifier(self._schema)
                ),
                (call_id,),
            )
            row: dict[str, Any] | None = await result.fetchone()
        return ToolCallHistory.model_validate(row) if row is not None else None

    async def list_facets(self) -> HistoryFacets:
        """Return distinct filter values observed in recorded tool calls."""
        schema_id: sql.Identifier = sql.Identifier(self._schema)
        async with self._pool.connection() as conn:
            servers_result: Any = await conn.execute(
                sql.SQL(
                    "SELECT DISTINCT server_name FROM {}.tool_calls ORDER BY 1"
                ).format(schema_id)
            )
            server_rows: list[dict[str, Any]] = await servers_result.fetchall()
            tools_result: Any = await conn.execute(
                sql.SQL(
                    "SELECT DISTINCT tool_name FROM {}.tool_calls ORDER BY 1"
                ).format(schema_id)
            )
            tool_rows: list[dict[str, Any]] = await tools_result.fetchall()
            keys_result: Any = await conn.execute(
                sql.SQL(
                    """
                    SELECT DISTINCT t.api_key_id AS id, t.api_key_name AS name
                      FROM {}.tool_calls AS t
                     ORDER BY 2
                    """
                ).format(schema_id)
            )
            key_rows: list[dict[str, Any]] = await keys_result.fetchall()
        return HistoryFacets(
            servers=[row["server_name"] for row in server_rows],
            tools=[row["tool_name"] for row in tool_rows],
            api_keys=[
                ApiKeyFacet(id=row["id"], name=row["name"]) for row in key_rows
            ],
        )
