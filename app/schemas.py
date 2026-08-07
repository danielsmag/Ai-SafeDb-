"""Response models for the gateway's own HTTP API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.connectors.models import SessionRecord
from app.models import McpServerConfig, ToolPolicy


class HealthResponse(BaseModel):
    status: str
    version: str
    servers: int


class ServerSummary(BaseModel):
    name: str
    description: str | None
    transport: str
    url: str
    tools: ToolPolicy

    @classmethod
    def from_config(cls, config: McpServerConfig, url: str) -> ServerSummary:
        return cls(
            name=config.name,
            description=config.description,
            transport=config.source.transport,
            url=url,
            tools=config.tools,
        )


class ServerListResponse(BaseModel):
    servers: list[ServerSummary]


class SessionDataKeyResponse(BaseModel):
    """Per-session secret used for keyed hashing of DB data."""

    session_id: UUID
    mcp_session_id: str
    data_key: str


class ApiKeyIdentityResponse(BaseModel):
    """Authenticated API-key identity safe for browser display."""

    name: str
    key_prefix: str


class SessionSummaryResponse(BaseModel):
    """Session metadata without the per-session data key."""

    id: UUID
    mcp_session_id: str
    server_name: str
    client_name: str | None
    client_version: str | None
    created_at: datetime
    last_seen_at: datetime
    closed_at: datetime | None

    @classmethod
    def from_record(cls, record: SessionRecord) -> SessionSummaryResponse:
        return cls(
            id=record.id,
            mcp_session_id=record.mcp_session_id,
            server_name=record.server_name,
            client_name=record.client_name,
            client_version=record.client_version,
            created_at=record.created_at,
            last_seen_at=record.last_seen_at,
            closed_at=record.closed_at,
        )


class SessionListResponse(BaseModel):
    sessions: list[SessionSummaryResponse]
