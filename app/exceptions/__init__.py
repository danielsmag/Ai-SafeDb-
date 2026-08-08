"""Public exception types for the MCP gateway."""

from app.exceptions.exceptions import (
    AuthError,
    ConfigError,
    DuplicatePolicyError,
    DuplicateServerError,
    GatewayError,
    LlmUnavailableError,
    MissingEnvVarError,
    PipelineExecutionError,
    PolicyViolationError,
    ProxyBuildError,
    ToolBlockedError,
    ToolGuardedError,
    UnknownTaskTypeError,
)

__all__: list[str] = [
    "AuthError",
    "ConfigError",
    "DuplicatePolicyError",
    "DuplicateServerError",
    "GatewayError",
    "LlmUnavailableError",
    "MissingEnvVarError",
    "PipelineExecutionError",
    "PolicyViolationError",
    "ProxyBuildError",
    "ToolBlockedError",
    "ToolGuardedError",
    "UnknownTaskTypeError",
]
