"""Tool-call history persistence against the gateway Postgres schema."""

from typing import Any, Protocol
from uuid import UUID

from psycopg import sql
from psycopg.types.json import Jsonb

from app.connectors.postgres import PostgresPool
from app.core.logging import logger
from app.services.history.models import ToolCallHistory, ToolCallHistoryPage


class HistoryStore(Protocol):
    """Persistence contract for gateway tool-call history."""

    async def ensure_schema(self) -> None: ...

    async def record(self, entry: ToolCallHistory) -> None: ...

    async def list_calls(
        self,
        api_key_id: UUID,
        *,
        limit: int,
        offset: int,
        server: str | None = None,
        session_id: UUID | None = None,
    ) -> ToolCallHistoryPage: ...

    async def get_call(
        self, api_key_id: UUID, call_id: UUID
    ) -> ToolCallHistory | None: ...


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
        api_key_id: UUID,
        *,
        limit: int,
        offset: int,
        server: str | None = None,
        session_id: UUID | None = None,
    ) -> ToolCallHistoryPage:
        """Return newest matching records scoped to one API-key principal."""
        predicates: list[sql.SQL] = [sql.SQL("api_key_id = %s")]
        params: list[object] = [api_key_id]
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

    async def get_call(
        self, api_key_id: UUID, call_id: UUID
    ) -> ToolCallHistory | None:
        """Return a call only when owned by the requesting API key."""
        async with self._pool.connection() as conn:
            result: Any = await conn.execute(
                sql.SQL(
                    """
                    SELECT *
                      FROM {}.tool_calls
                     WHERE id = %s AND api_key_id = %s
                    """
                ).format(sql.Identifier(self._schema)),
                (call_id, api_key_id),
            )
            row: dict[str, Any] | None = await result.fetchone()
        return ToolCallHistory.model_validate(row) if row is not None else None
