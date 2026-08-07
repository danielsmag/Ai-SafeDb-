"""Domain models for persisted gateway tool-call history."""

from datetime import UTC, datetime
from typing import Any, ClassVar, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field

type ToolCallStatus = Literal["ok", "blocked", "error"]


class ToolCallHistory(BaseModel):
    """Persisted audit record for one MCP tool call."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    id: UUID = Field(default_factory=uuid4)
    session_id: UUID
    mcp_session_id: str
    api_key_id: UUID
    api_key_name: str
    server_name: str
    tool_name: str
    original_arguments: dict[str, Any] = Field(default_factory=dict)
    original_sql: list[str] = Field(default_factory=list)
    executed_sql: list[str] = Field(default_factory=list)
    expanded_stars: bool = False
    dropped_columns: list[str] = Field(default_factory=list)
    hashed_columns: list[str] = Field(default_factory=list)
    masked_fields: list[str] = Field(default_factory=list)
    removed_fields: list[str] = Field(default_factory=list)
    call_decision: str | None = None
    result_decision: str | None = None
    status: ToolCallStatus = "ok"
    error: str | None = None
    duration_ms: float = Field(default=0.0, ge=0)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ToolCallHistoryPage(BaseModel):
    """One page of history plus total matching row count."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    items: list[ToolCallHistory]
    total: int = Field(ge=0)
