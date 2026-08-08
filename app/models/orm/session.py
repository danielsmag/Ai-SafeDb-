"""SQLModel mappings for API keys and MCP client sessions."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel

from app.models.orm.base import APP_SCHEMA_TOKEN, utc_now


class ApiKeyORM(SQLModel, table=True):
    """Hashed API key row."""

    __tablename__: ClassVar[str] = "api_keys"
    __table_args__: ClassVar[dict[str, str]] = {"schema": APP_SCHEMA_TOKEN}

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    name: str = Field(sa_column=Column(Text, nullable=False))
    key_prefix: str = Field(sa_column=Column(Text, nullable=False))
    key_hash: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    revoked_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    last_used_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    user_id: UUID | None = Field(
        default=None,
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey(f"{APP_SCHEMA_TOKEN}.users.id"),
            nullable=True,
        ),
    )


class SessionORM(SQLModel, table=True):
    """Recognized MCP client session row."""

    __tablename__: ClassVar[str] = "sessions"
    __table_args__: ClassVar[tuple[Index, dict[str, str]]] = (
        Index("sessions_api_key_id_idx", "api_key_id"),
        {"schema": APP_SCHEMA_TOKEN},
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    mcp_session_id: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    api_key_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey(f"{APP_SCHEMA_TOKEN}.api_keys.id"),
            nullable=False,
        )
    )
    server_name: str = Field(sa_column=Column(Text, nullable=False))
    data_key: str = Field(sa_column=Column(Text, nullable=False))
    client_name: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    client_version: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    created_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    last_seen_at: datetime = Field(
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    closed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


__all__: list[str] = [
    "ApiKeyORM",
    "SessionORM",
]
