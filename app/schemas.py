"""Response models for the gateway's own HTTP API."""

from pydantic import BaseModel

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
