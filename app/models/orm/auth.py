"""SQLModel mappings for web-console auth tables."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID, uuid4

from sqlalchemy import Boolean, Column, DateTime, ForeignKey, Index, Text, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlmodel import Field, SQLModel

from app.models.orm.base import APP_SCHEMA_TOKEN, utc_now


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
        default_factory=utc_now,
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
    expires_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False)
    )


__all__: list[str] = [
    "UserORM",
    "WebSessionORM",
]
