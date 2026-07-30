"""Public exception types for the MCP gateway."""

from app.exceptions.exceptions import (
    ConfigError,
    DuplicateServerError,
    GatewayError,
    MissingEnvVarError,
    ProxyBuildError,
    ToolBlockedError,
)

__all__: list[str] = [
    "ConfigError",
    "DuplicateServerError",
    "GatewayError",
    "MissingEnvVarError",
    "ProxyBuildError",
    "ToolBlockedError",
]
