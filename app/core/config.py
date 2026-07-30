"""Validated runtime configuration for the MCP gateway."""

from pathlib import Path
from typing import ClassVar, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class AppSettings(BaseSettings):
    """Immutable settings loaded from environment variables and ``.env``."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        frozen=True,
        validate_default=True,
    )

    config_dir: Path = Path("mcp-servers")
    mount_prefix: str = "/mcp"
    public_base_url: str = "http://localhost:8000"
    log_level: LogLevel = "INFO"

    stateless_http: bool = False
    json_response: bool = False

    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_origins: list[str] = Field(default_factory=list)

    @field_validator("mount_prefix")
    @classmethod
    def normalize_mount_prefix(cls, value: str) -> str:
        """Normalize the MCP mount prefix and reject the root path."""
        normalized: str = f"/{value.strip('/')}"
        if normalized == "/":
            raise ValueError("mount_prefix must not be the root path")
        return normalized

    @field_validator("public_base_url")
    @classmethod
    def normalize_public_base_url(cls, value: str) -> str:
        """Remove trailing slashes while rejecting an empty base URL."""
        normalized: str = value.rstrip("/")
        if not normalized:
            raise ValueError("public_base_url must not be empty")
        return normalized
