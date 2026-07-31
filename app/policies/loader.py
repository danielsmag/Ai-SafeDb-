"""Loading of validated YAML policy definitions."""

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import ValidationError

from app.exceptions import ConfigError, DuplicatePolicyError, MissingEnvVarError
from app.policies.models import Policy, SqlPolicy

_YAML_SUFFIXES: tuple[str, str] = (".yaml", ".yml")
_ENV_PLACEHOLDER: re.Pattern[str] = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}"
)


class PolicyLoader:
    """Read, expand, and validate policy YAML files."""

    def __init__(
        self,
        policies_dir: Path,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._policies_dir: Path = policies_dir
        self._environ: Mapping[str, str] = (
            environ if environ is not None else os.environ
        )

    @property
    def policies_dir(self) -> Path:
        return self._policies_dir

    def load(self) -> dict[str, Policy]:
        if not self._policies_dir.is_dir():
            raise ConfigError(self._policies_dir, "policy directory does not exist")

        policies: dict[str, Policy] = {}
        sources: dict[str, Path] = {}
        for path in self._iter_policy_files():
            document: dict[str, Any] = self._read_document(path)
            document.setdefault("name", path.stem)
            resolved: Any = self._expand(document, path)
            try:
                policy: Policy = SqlPolicy.model_validate(resolved)
            except ValidationError as err:
                raise ConfigError(path, f"invalid policy definition: {err}") from err

            first: Path | None = sources.get(policy.name)
            if first is not None:
                raise DuplicatePolicyError(policy.name, first, path)
            sources[policy.name] = path
            policies[policy.name] = policy
        return policies

    def _iter_policy_files(self) -> list[Path]:
        files: list[Path] = [
            path
            for path in self._policies_dir.iterdir()
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
