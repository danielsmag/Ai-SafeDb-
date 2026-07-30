"""Application settings, sourced from environment variables with a `GATEWAY_` prefix."""

from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]


class AppSettings(BaseSettings):
    """Runtime configuration for the gateway."""

    model_config = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    config_dir: Path = Path("mcp-servers")
    mount_prefix: str = "/mcp"
    public_base_url: str = "http://localhost:8000"
    log_level: LogLevel = "INFO"

    # Streamable-HTTP transport tuning, applied to every mounted proxy.
    stateless_http: bool = False
    json_response: bool = False

    # DNS-rebinding protection for the MCP endpoints. Add the hostnames the
    # gateway is reached through when it runs behind a proxy or in a container.
    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_origins: list[str] = Field(default_factory=list)

    @field_validator("mount_prefix")
    @classmethod
    def _normalize_mount_prefix(cls, value: str) -> str:
        normalized = "/" + value.strip("/")
        if normalized == "/":
            raise ValueError("mount_prefix must not be the root path")
        return normalized

    @field_validator("public_base_url")
    @classmethod
    def _strip_trailing_slash(cls, value: str) -> str:
        return value.rstrip("/")
