"""Exception hierarchy for the gateway."""

from pathlib import Path

from fastmcp.exceptions import ToolError


class GatewayError(Exception):
    """Base error for the MCP gateway."""


class ConfigError(GatewayError):
    """A server definition file is missing, unreadable, or invalid."""

    def __init__(self, path: Path, message: str) -> None:
        self.path: Path = path
        super().__init__(f"{path}: {message}")


class MissingEnvVarError(ConfigError):
    """A `${VAR}` placeholder in a server definition has no value."""

    def __init__(self, path: Path, var_name: str) -> None:
        self.var_name: str = var_name
        super().__init__(path, f"environment variable {var_name!r} is not set")


class DuplicateServerError(GatewayError):
    """Two server definitions claim the same name."""

    def __init__(self, name: str, first: Path, second: Path) -> None:
        self.name: str = name
        self.first: Path = first
        self.second: Path = second
        super().__init__(f"duplicate server name {name!r} in {first} and {second}")


class ProxyBuildError(GatewayError):
    """A proxy could not be constructed for a server definition."""

    def __init__(self, server_name: str, message: str) -> None:
        self.server_name: str = server_name
        super().__init__(f"{server_name}: {message}")


class LlmUnavailableError(GatewayError):
    """A local model request failed or returned an invalid response."""


class ToolBlockedError(GatewayError, ToolError):
    """A tool call was rejected by the server's tool policy.

    Subclasses `ToolError` so FastMCP reports the reason to the client instead of
    masking it as an internal error.
    """

    def __init__(self, server_name: str, tool_name: str) -> None:
        self.server_name: str = server_name
        self.tool_name: str = tool_name
        super().__init__(
            f"tool {tool_name!r} is not exposed by gateway server {server_name!r}"
        )


class ToolGuardedError(GatewayError, ToolError):
    """A safety guard rejected a tool call or its result."""

    def __init__(self, server_name: str, tool_name: str, reason: str) -> None:
        self.server_name: str = server_name
        self.tool_name: str = tool_name
        self.reason: str = reason
        super().__init__(
            f"safety guard blocked tool {tool_name!r} on server "
            f"{server_name!r}: {reason}"
        )
