"""Validated red-team scenario loading."""

from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.exceptions import ConfigError


class RedTeamScenario(BaseModel):
    """One bounded adversarial objective."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]*$")
    objective: str = Field(min_length=1)
    server_url: str = "http://localhost:8000/mcp/postgres"
    max_steps: int = Field(default=8, ge=1, le=50)
    timeout_seconds: float = Field(default=120, gt=0)


class ScenarioLoader:
    """Load one red-team scenario from YAML."""

    def load(self, path: Path) -> RedTeamScenario:
        try:
            raw: str = path.read_text(encoding="utf-8")
            document: Any = yaml.safe_load(raw)
        except OSError as err:
            raise ConfigError(path, f"cannot read scenario: {err}") from err
        except yaml.YAMLError as err:
            raise ConfigError(path, f"invalid scenario YAML: {err}") from err
        try:
            return RedTeamScenario.model_validate(document)
        except ValidationError as err:
            raise ConfigError(path, f"invalid scenario: {err}") from err
