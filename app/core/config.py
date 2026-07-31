"""Validated runtime configuration for the MCP gateway."""

from pathlib import Path
from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type GuardErrorMode = Literal["block", "allow"]


class LlmSettings(BaseModel):
    """OpenAI-compatible local model endpoint settings."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    base_url: str = "http://localhost:11434/v1"
    api_key: str = "not-needed"
    guard_model: str = "qwen3:4b"
    agent_model: str = "qwen3.6:35b-a3b"
    timeout_seconds: float = Field(default=10.0, gt=0)
    max_concurrency: int = Field(default=2, ge=1)
    keep_alive: str = "10m"


class GuardSettings(BaseModel):
    """Safety guard behavior and failure policy."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    enabled: bool = False
    on_error: GuardErrorMode = "block"
    inspect_results: bool = True
    cache_ttl_seconds: float = Field(default=300.0, ge=0)


class AppSettings(BaseSettings):
    """Immutable settings loaded from environment variables and ``.env``."""

    model_config: ClassVar[SettingsConfigDict] = SettingsConfigDict(
        env_prefix="GATEWAY_",
        env_file=".env",
        env_file_encoding="utf-8",
        env_nested_delimiter="__",
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
    llm: LlmSettings = Field(default_factory=LlmSettings)
    guard: GuardSettings = Field(default_factory=GuardSettings)

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
