"""Validated runtime configuration for the MCP gateway."""

import os
import re
from pathlib import Path
from typing import Any, ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

type LogLevel = Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]
type GuardErrorMode = Literal["block", "allow"]

_SCHEMA_NAME_RE: re.Pattern[str] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class LlmSettings(BaseModel):
    """OpenAI-compatible local model endpoint settings."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    base_url: str = "http://localhost:11434/v1"
    api_key: str = "not-needed"
    guard_model: str = "qwen3:4b"
    rewrite_model: str = "qwen3:4b"
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


class SessionSettings(BaseModel):
    """MCP session recognition and lifetime policy."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    # 0 disables idle expiry. Default: 24 hours without requests.
    idle_ttl_seconds: float = Field(default=86_400.0, ge=0)


class AuthSettings(BaseModel):
    """Web-console cookie session policy."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    session_ttl_seconds: float = Field(default=86_400.0, gt=0)
    cookie_name: str = Field(default="aisafedb_session", min_length=1)
    cookie_secure: bool = False


class DatabaseSettings(BaseModel):
    """Postgres connection used for gateway API keys and MCP sessions."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    host: str = "localhost"
    port: int = Field(default=5432, ge=1, le=65535)
    user: str = "aisafe"
    password: str = "aisafe"
    name: str = "aisafedb"
    schema_name: str = "aisafedb"

    @model_validator(mode="before")
    @classmethod
    def apply_safe_db_schema_env(cls, data: Any) -> Any:
        """Prefer top-level ``SAFE_DB_SCHEMA`` when the nested field is unset."""
        if not isinstance(data, dict):
            return data
        if data.get("schema_name"):
            return data
        env_schema: str | None = os.environ.get("SAFE_DB_SCHEMA")
        if env_schema:
            return {**data, "schema_name": env_schema}
        return data

    @field_validator("schema_name")
    @classmethod
    def validate_schema_name(cls, value: str) -> str:
        """Reject identifiers that cannot be used safely in DDL."""
        if not _SCHEMA_NAME_RE.fullmatch(value):
            raise ValueError(
                f"schema_name must match [A-Za-z_][A-Za-z0-9_]* (got {value!r})"
            )
        return value

    def dsn(self) -> str:
        """Build a libpq connection string for psycopg."""
        return (
            f"postgresql://{self.user}:{self.password}"
            f"@{self.host}:{self.port}/{self.name}"
        )


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
    policies_dir: Path = Path("policies")
    mount_prefix: str = "/mcp"
    public_base_url: str = "http://localhost:8000"
    log_level: LogLevel = "INFO"

    stateless_http: bool = False
    json_response: bool = False

    allowed_hosts: list[str] = Field(default_factory=list)
    allowed_origins: list[str] = Field(default_factory=list)
    llm: LlmSettings = Field(default_factory=LlmSettings)
    guard: GuardSettings = Field(default_factory=GuardSettings)
    database: DatabaseSettings = Field(default_factory=DatabaseSettings)
    session: SessionSettings = Field(default_factory=SessionSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)

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
