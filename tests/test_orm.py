"""Unit checks for app-owned SQLModel metadata."""

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.sql.schema import Table
from sqlmodel import SQLModel

from app.connectors.orm_models import APP_SCHEMA_TOKEN
from app.core.config import DatabaseSettings


def test_orm_metadata_contains_only_app_managed_tables() -> None:
    table_names: set[str] = set(SQLModel.metadata.tables)

    assert table_names == {
        f"{APP_SCHEMA_TOKEN}.api_keys",
        f"{APP_SCHEMA_TOKEN}.sessions",
        f"{APP_SCHEMA_TOKEN}.tool_calls",
        f"{APP_SCHEMA_TOKEN}.users",
        f"{APP_SCHEMA_TOKEN}.web_sessions",
    }
    tables: list[Table] = list(SQLModel.metadata.tables.values())
    assert all(table.schema == APP_SCHEMA_TOKEN for table in tables)
    assert f"{APP_SCHEMA_TOKEN}.customers" not in table_names


async def test_async_dsn_uses_psycopg_sqlalchemy_dialect() -> None:
    settings: DatabaseSettings = DatabaseSettings()
    engine: AsyncEngine = create_async_engine(settings.async_dsn())

    assert settings.async_dsn().startswith("postgresql+psycopg://")
    assert engine.dialect.name == "postgresql"
    assert engine.dialect.driver == "psycopg"
    await engine.dispose()
