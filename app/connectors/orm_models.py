"""SQLModel mappings for gateway-owned application tables."""

from datetime import UTC, datetime
from typing import Any, ClassVar
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel

APP_SCHEMA_TOKEN: str = "app"


def _utc_now() -> datetime:
    return datetime.now(UTC)


class UserORM(SQLModel, table=True):
    """Web-console user row."""

    __tablename__: ClassVar[str] = "users"
    __table_args__: ClassVar[dict[str, str]] = {"schema": APP_SCHEMA_TOKEN}

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    username: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    password_hash: str = Field(sa_column=Column(Text, nullable=False))
    is_admin: bool = Field(
        default=False,
        sa_column=Column(
            Boolean,
            nullable=False,
            server_default=text("FALSE"),
        ),
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    disabled_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )


class WebSessionORM(SQLModel, table=True):
    """Server-side browser session row."""

    __tablename__: ClassVar[str] = "web_sessions"
    __table_args__: ClassVar[tuple[Index, dict[str, str]]] = (
        Index("web_sessions_user_id_idx", "user_id"),
        {"schema": APP_SCHEMA_TOKEN},
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    token_hash: str = Field(sa_column=Column(Text, nullable=False, unique=True))
    user_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey(f"{APP_SCHEMA_TOKEN}.users.id"),
            nullable=False,
        )
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    last_seen_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


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
        default_factory=_utc_now,
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
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )
    last_seen_at: datetime = Field(
        default_factory=_utc_now,
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


class ToolCallORM(SQLModel, table=True):
    """Immutable gateway tool-call audit row."""

    __tablename__: ClassVar[str] = "tool_calls"
    __table_args__: ClassVar[tuple[Index, Index, CheckConstraint, dict[str, str]]] = (
        Index("tool_calls_api_key_created_idx", "api_key_id", text("created_at DESC")),
        Index("tool_calls_session_id_idx", "session_id"),
        CheckConstraint(
            "status IN ('ok', 'blocked', 'error')",
            name="tool_calls_status_check",
        ),
        {"schema": APP_SCHEMA_TOKEN},
    )

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(PGUUID(as_uuid=True), primary_key=True),
    )
    session_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey(f"{APP_SCHEMA_TOKEN}.sessions.id"),
            nullable=False,
        )
    )
    mcp_session_id: str = Field(sa_column=Column(Text, nullable=False))
    api_key_id: UUID = Field(
        sa_column=Column(
            PGUUID(as_uuid=True),
            ForeignKey(f"{APP_SCHEMA_TOKEN}.api_keys.id"),
            nullable=False,
        )
    )
    api_key_name: str = Field(sa_column=Column(Text, nullable=False))
    server_name: str = Field(sa_column=Column(Text, nullable=False))
    tool_name: str = Field(sa_column=Column(Text, nullable=False))
    original_arguments: dict[str, Any] = Field(
        default_factory=dict,
        sa_column=Column(
            JSONB,
            nullable=False,
            server_default=text("'{}'::jsonb"),
        ),
    )
    original_sql: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(String),
            nullable=False,
            server_default=text("'{}'::text[]"),
        ),
    )
    executed_sql: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(String),
            nullable=False,
            server_default=text("'{}'::text[]"),
        ),
    )
    expanded_stars: bool = Field(
        default=False,
        sa_column=Column(Boolean, nullable=False, server_default=text("FALSE")),
    )
    dropped_columns: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(String),
            nullable=False,
            server_default=text("'{}'::text[]"),
        ),
    )
    hashed_columns: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(String),
            nullable=False,
            server_default=text("'{}'::text[]"),
        ),
    )
    masked_fields: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(String),
            nullable=False,
            server_default=text("'{}'::text[]"),
        ),
    )
    removed_fields: list[str] = Field(
        default_factory=list,
        sa_column=Column(
            ARRAY(String),
            nullable=False,
            server_default=text("'{}'::text[]"),
        ),
    )
    call_decision: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    result_decision: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    status: str = Field(default="ok", sa_column=Column(Text, nullable=False))
    error: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    duration_ms: float = Field(
        default=0.0,
        sa_column=Column(Float, nullable=False, server_default=text("0")),
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )


__all__: list[str] = [
    "APP_SCHEMA_TOKEN",
    "ApiKeyORM",
    "SessionORM",
    "ToolCallORM",
    "UserORM",
    "WebSessionORM",
]
