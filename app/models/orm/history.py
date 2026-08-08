"""SQLModel mappings for gateway tool-call audit tables."""

from datetime import datetime
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

from app.models.orm.base import APP_SCHEMA_TOKEN, utc_now


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
        default_factory=utc_now,
        sa_column=Column(
            DateTime(timezone=True),
            nullable=False,
            server_default=func.now(),
        ),
    )


__all__: list[str] = [
    "ToolCallORM",
]
