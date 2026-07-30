"""Schema of the YAML files that describe source MCP servers."""

from fnmatch import fnmatch
from typing import Annotated, Literal

from pydantic import AnyHttpUrl, BaseModel, ConfigDict, Field

SERVER_NAME_PATTERN = r"^[a-z0-9][a-z0-9._-]*$"


class HttpSource(BaseModel):
    """A source MCP server reachable over HTTP."""

    model_config = ConfigDict(extra="forbid")

    transport: Literal["http", "sse"] = "http"
    url: AnyHttpUrl
    headers: dict[str, str] = Field(default_factory=dict)
    read_timeout_seconds: float | None = Field(default=None, gt=0)


class StdioSource(BaseModel):
    """A source MCP server the gateway launches as a child process."""

    model_config = ConfigDict(extra="forbid")

    transport: Literal["stdio"]
    command: str = Field(min_length=1)
    args: list[str] = Field(default_factory=list)
    env: dict[str, str] = Field(default_factory=dict)
    cwd: str | None = None


McpSource = Annotated[HttpSource | StdioSource, Field(discriminator="transport")]


class ToolPolicy(BaseModel):
    """Which of the source server's tools the gateway exposes.

    Names may use shell-style wildcards (`read_*`). An empty `allow` list means
    every tool is allowed; `block` always wins over `allow`.
    """

    model_config = ConfigDict(extra="forbid")

    allow: list[str] = Field(default_factory=list)
    block: list[str] = Field(default_factory=list)

    def permits(self, tool_name: str) -> bool:
        if any(fnmatch(tool_name, pattern) for pattern in self.block):
            return False
        if not self.allow:
            return True
        return any(fnmatch(tool_name, pattern) for pattern in self.allow)


class McpServerConfig(BaseModel):
    """One YAML file: a source MCP server plus the policy applied to it."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(pattern=SERVER_NAME_PATTERN, max_length=64)
    enabled: bool = True
    description: str | None = None
    source: McpSource
    tools: ToolPolicy = Field(default_factory=ToolPolicy)

    def mount_path(self, mount_prefix: str) -> str:
        return f"{mount_prefix}/{self.name}"
