"""Loading of source MCP server definitions from a dedicated folder."""

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.core.logging import logger
from app.exceptions import ConfigError, DuplicateServerError, MissingEnvVarError
from app.models import McpServerConfig

_YAML_SUFFIXES: tuple[str, str] = (".yaml", ".yml")

# ${VAR} or ${VAR:-fallback}
_ENV_PLACEHOLDER: re.Pattern[str] = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}"
)


class ConfigLoader:
    """Reads and validates every YAML server definition in a folder.

    Secrets stay out of the YAML: `${VAR}` placeholders are resolved from the
    environment, optionally with a `${VAR:-fallback}` default.
    """

    def __init__(
        self,
        config_dir: Path,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._config_dir: Path = config_dir
        self._environ: Mapping[str, str] = (
            environ if environ is not None else os.environ
        )

    @property
    def config_dir(self) -> Path:
        return self._config_dir

    def load(self) -> list[McpServerConfig]:
        """Return the enabled server definitions, sorted by name.

        Raises:
            ConfigError: the folder is missing or a file is invalid.
            DuplicateServerError: two files define the same server name.
        """
        if not self._config_dir.is_dir():
            raise ConfigError(self._config_dir, "config directory does not exist")

        seen: dict[str, Path] = {}
        configs: list[McpServerConfig] = []
        for path in self._iter_config_files():
            document: dict[str, Any] = self._read_document(path)
            # Checked before validation and `${VAR}` expansion so that disabled
            # files can stay in the folder as templates with unset secrets.
            if not document.get("enabled", True):
                logger.info("Skipping disabled server definition %s", path.name)
                continue

            config: McpServerConfig = self._build_config(path, document)
            first: Path | None = seen.get(config.name)
            if first is not None:
                raise DuplicateServerError(config.name, first, path)
            seen[config.name] = path
            configs.append(config)

        return sorted(configs, key=lambda config: config.name)

    def _iter_config_files(self) -> list[Path]:
        files: list[Path] = [
            path
            for path in self._config_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in _YAML_SUFFIXES
            and not path.name.startswith(".")
        ]
        return sorted(files)

    def _read_document(self, path: Path) -> dict[str, Any]:
        try:
            raw: str = path.read_text(encoding="utf-8")
        except OSError as err:
            raise ConfigError(path, f"cannot read file: {err}") from err

        try:
            document: Any = yaml.safe_load(raw)
        except yaml.YAMLError as err:
            raise ConfigError(path, f"invalid YAML: {err}") from err

        if document is None:
            raise ConfigError(path, "file is empty")
        if not isinstance(document, dict):
            raise ConfigError(path, "top-level YAML value must be a mapping")
        return document

    def _build_config(self, path: Path, document: dict[str, Any]) -> McpServerConfig:
        document.setdefault("name", path.stem)
        resolved: Any = self._expand(document, path)

        try:
            return McpServerConfig.model_validate(resolved)
        except ValidationError as err:
            raise ConfigError(path, f"invalid server definition: {err}") from err

    def _expand(self, value: Any, path: Path) -> Any:
        if isinstance(value, str):
            return self._expand_str(value, path)
        if isinstance(value, dict):
            return {key: self._expand(item, path) for key, item in value.items()}
        if isinstance(value, list):
            return [self._expand(item, path) for item in value]
        return value

    def _expand_str(self, value: str, path: Path) -> str:
        def replace(match: re.Match[str]) -> str:
            var_name: str = match.group(1)
            fallback: str | None = match.group(2)
            resolved: str | None = self._environ.get(var_name)
            if resolved is not None:
                return resolved
            if fallback is not None:
                return fallback
            raise MissingEnvVarError(path, var_name)

        return _ENV_PLACEHOLDER.sub(replace, value)
