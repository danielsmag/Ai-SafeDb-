"""Async SQLModel database lifecycle for gateway application state."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.sql.elements import TextClause
from sqlmodel import SQLModel

from app.models.orm import APP_SCHEMA_TOKEN
from app.core.config import DatabaseSettings
from app.core.logging import logger


class Database:
    """Own async SQLAlchemy engine and request-independent session factory."""

    def __init__(self, settings: DatabaseSettings) -> None:
        self._settings: DatabaseSettings = settings
        self._engine: AsyncEngine | None = None
        self._session_factory: async_sessionmaker[AsyncSession] | None = None

    @property
    def schema_name(self) -> str:
        return self._settings.schema_name

    async def open(self) -> None:
        """Open engine and session factory if not already open."""
        if self._engine is not None:
            return
        execution_options: dict[str, dict[str, str]] = {
            "schema_translate_map": {
                APP_SCHEMA_TOKEN: self._settings.schema_name,
            }
        }
        engine: AsyncEngine = create_async_engine(
            self._settings.async_dsn(),
            pool_size=10,
            max_overflow=0,
            execution_options=execution_options,
        )
        self._engine = engine
        self._session_factory = async_sessionmaker(
            bind=engine,
            expire_on_commit=False,
        )
        logger.info(
            "Opened SQLModel database database=%r schema=%r",
            self._settings.name,
            self._settings.schema_name,
        )

    async def close(self) -> None:
        """Dispose engine if open."""
        engine: AsyncEngine | None = self._engine
        if engine is None:
            return
        await engine.dispose()
        self._engine = None
        self._session_factory = None
        logger.info("Closed SQLModel database")

    async def create_all(self) -> None:
        """Create configured app schema and missing ORM-managed tables."""
        engine: AsyncEngine = self._require_engine()
        schema_statement: TextClause = text(
            f'CREATE SCHEMA IF NOT EXISTS "{self._settings.schema_name}"'
        )
        async with engine.begin() as connection:
            await connection.execute(schema_statement)
            await connection.run_sync(SQLModel.metadata.create_all)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        """Yield one transactional ORM session."""
        session_factory: async_sessionmaker[AsyncSession] | None = (
            self._session_factory
        )
        if session_factory is None:
            raise RuntimeError("Database is not open")
        async with session_factory() as session:
            yield session

    def _require_engine(self) -> AsyncEngine:
        engine: AsyncEngine | None = self._engine
        if engine is None:
            raise RuntimeError("Database is not open")
        return engine


__all__: list[str] = ["Database"]
