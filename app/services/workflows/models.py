"""Schema of the YAML files that describe workflow dependency chains."""

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models import SERVER_NAME_PATTERN

type SourceKind = Literal["postgres", "mysql", "sqlite", "http", "other"]
type OutputTransport = Literal["http", "sse", "stdio"]
type WorkflowNodeKind = Literal["source", "mcp", "policy", "output"]


class SourceServerDefinition(BaseModel):
    """One YAML file in the sources folder: an upstream system."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    name: str = Field(pattern=SERVER_NAME_PATTERN, max_length=64)
    enabled: bool = True
    description: str | None = None
    kind: SourceKind = "other"
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str | None = None


class OutputEndpointDefinition(BaseModel):
    """One YAML file in the outputs folder: a protected MCP target endpoint."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    name: str = Field(pattern=SERVER_NAME_PATTERN, max_length=64)
    enabled: bool = True
    description: str | None = None
    transport: OutputTransport = "http"
    url: str | None = None


class WorkflowDefinition(BaseModel):
    """One YAML file in the workflows folder: source -> mcp -> policies -> output."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    name: str = Field(pattern=SERVER_NAME_PATTERN, max_length=64)
    enabled: bool = True
    description: str | None = None
    source: str = Field(pattern=SERVER_NAME_PATTERN)
    mcp_server: str = Field(pattern=SERVER_NAME_PATTERN)
    policies: list[str] = Field(default_factory=list)
    output: str = Field(pattern=SERVER_NAME_PATTERN)


class WorkflowCatalog(BaseModel):
    """Every loaded workflow definition plus its referenced building blocks."""

    sources: dict[str, SourceServerDefinition] = Field(default_factory=dict)
    outputs: dict[str, OutputEndpointDefinition] = Field(default_factory=dict)
    workflows: dict[str, WorkflowDefinition] = Field(default_factory=dict)
