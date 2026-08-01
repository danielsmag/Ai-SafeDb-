"""Domain models for API keys and recognized MCP sessions."""

from datetime import datetime
from typing import ClassVar
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class ApiKey(BaseModel):
    """An active (or revoked) API key principal."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    name: str
    key_prefix: str
    key_hash: str
    created_at: datetime
    revoked_at: datetime | None = None
    last_used_at: datetime | None = None


class ClientInfo(BaseModel):
    """MCP ``clientInfo`` captured at initialize."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    name: str | None = None
    version: str | None = None


class SessionRecord(BaseModel):
    """A recognized MCP client session bound to an API key."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    id: UUID
    mcp_session_id: str
    api_key_id: UUID
    api_key_name: str = Field(description="Denormalized key name for logging")
    server_name: str
    data_key: str = Field(
        description="Per-session secret for future keyed hashing of DB data"
    )
    client_name: str | None = None
    client_version: str | None = None
    created_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None = None
