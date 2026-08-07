"""Response models for the gateway's own HTTP API."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

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


class LoginRequest(BaseModel):
    """Web-console credentials."""

    username: str = Field(min_length=1)
    password: str = Field(min_length=1)


class UserIdentityResponse(BaseModel):
    """Authenticated web-console identity."""

    username: str
    is_admin: bool
    created_at: datetime


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


class UserResponse(BaseModel):
    """User info without password hash."""

    id: UUID
    username: str
    is_admin: bool
    created_at: datetime
    disabled_at: datetime | None


class UserListResponse(BaseModel):
    users: list[UserResponse]


class CreateUserRequest(BaseModel):
    """Payload for creating a new user."""

    username: str = Field(min_length=1, max_length=64)
    password: str = Field(min_length=6, max_length=128)
    is_admin: bool = False


class UpdateUserRequest(BaseModel):
    """Partial update payload for a user."""

    password: str | None = Field(default=None, min_length=6, max_length=128)
    is_admin: bool | None = None
    disabled: bool | None = None


class PolicySummary(BaseModel):
    """Policy overview for admin display."""

    name: str
    type: str
    dialect: str
    read_only: bool
    denied_keywords: list[str]
    tables_count: int
    pii_rules_count: int


class PolicyListResponse(BaseModel):
    policies: list[PolicySummary]


class WorkflowNodeResponse(BaseModel):
    """One box in a workflow DAG."""

    id: str
    kind: str
    label: str
    sublabel: str | None
    missing: bool
    details: dict[str, str]
    yaml: str | None


class WorkflowEdgeResponse(BaseModel):
    """One dependency arrow between two workflow DAG nodes."""

    from_id: str
    to_id: str


class WorkflowGraphResponse(BaseModel):
    """Full DAG of a workflow, ready for rendering."""

    nodes: list[WorkflowNodeResponse]
    edges: list[WorkflowEdgeResponse]


class WorkflowSummaryResponse(BaseModel):
    """Workflow overview plus its resolved dependency graph."""

    name: str
    enabled: bool
    description: str | None
    source: str
    mcp_server: str
    policies: list[str]
    output: str
    valid: bool
    graph: WorkflowGraphResponse


class WorkflowListResponse(BaseModel):
    workflows: list[WorkflowSummaryResponse]
