"""Postgres connection pool for gateway application state."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final

from psycopg import AsyncConnection
from psycopg.rows import dict_row
from psycopg_pool import AsyncConnectionPool

from app.core.config import DatabaseSettings
from app.core.logging import logger

_MIN_SIZE: Final[int] = 1
_MAX_SIZE: Final[int] = 10


class PostgresPool:
    """Lifecycle wrapper around an async psycopg connection pool."""

    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings: DatabaseSettings = settings
        self._pool: AsyncConnectionPool | None = None

    @property
    def settings(self) -> DatabaseSettings:
        return self._settings

    @property
    def schema_name(self) -> str:
        return self._settings.schema_name

    async def open(self) -> None:
        """Open the pool if it is not already open."""
        if self._pool is not None:
            return
        pool: AsyncConnectionPool = AsyncConnectionPool(
            conninfo=self._settings.dsn(),
            min_size=_MIN_SIZE,
            max_size=_MAX_SIZE,
            kwargs={"row_factory": dict_row},
            open=False,
        )
        await pool.open()
        self._pool = pool
        logger.info(
            "Opened Postgres pool database=%r schema=%r",
            self._settings.name,
            self._settings.schema_name,
        )

    async def close(self) -> None:
        """Close the pool if it is open."""
        if self._pool is None:
            return
        await self._pool.close()
        self._pool = None
        logger.info("Closed Postgres pool")

    @asynccontextmanager
    async def connection(self) -> AsyncIterator[AsyncConnection]:
        """Borrow a connection from the pool."""
        if self._pool is None:
            raise RuntimeError("Postgres pool is not open")
        async with self._pool.connection() as conn:
            yield conn
