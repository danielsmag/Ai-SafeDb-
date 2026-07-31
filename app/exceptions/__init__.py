"""Public exception types for the MCP gateway."""

from app.exceptions.exceptions import (
    ConfigError,
    DuplicateServerError,
    GatewayError,
    LlmUnavailableError,
    MissingEnvVarError,
    ProxyBuildError,
    ToolBlockedError,
    ToolGuardedError,
)

__all__: list[str] = [
    "ConfigError",
    "DuplicateServerError",
    "GatewayError",
    "LlmUnavailableError",
    "MissingEnvVarError",
    "ProxyBuildError",
    "ToolBlockedError",
    "ToolGuardedError",
]
