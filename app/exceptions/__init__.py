"""Public exception types for the MCP gateway."""

from app.exceptions.exceptions import (
    ConfigError,
    DuplicatePolicyError,
    DuplicateServerError,
    GatewayError,
    LlmUnavailableError,
    MissingEnvVarError,
    PolicyViolationError,
    ProxyBuildError,
    ToolBlockedError,
    ToolGuardedError,
)

__all__: list[str] = [
    "ConfigError",
    "DuplicatePolicyError",
    "DuplicateServerError",
    "GatewayError",
    "LlmUnavailableError",
    "MissingEnvVarError",
    "PolicyViolationError",
    "ProxyBuildError",
    "ToolBlockedError",
    "ToolGuardedError",
]
