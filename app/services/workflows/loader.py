"""Loading of workflow, source, and output endpoint YAML definitions."""

import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ValidationError

from app.core.logging import logger
from app.exceptions import ConfigError, MissingEnvVarError
from app.services.workflows.models import (
    OutputEndpointDefinition,
    SourceServerDefinition,
    WorkflowCatalog,
    WorkflowDefinition,
)

_YAML_SUFFIXES: tuple[str, str] = (".yaml", ".yml")

# ${VAR} or ${VAR:-fallback}
_ENV_PLACEHOLDER: re.Pattern[str] = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}"
)


class WorkflowLoader:
    """Read and validate the workflow catalog from three YAML folders.

    A missing folder yields an empty section instead of an error so the
    gateway keeps working for deployments that have not adopted workflows.
    """

    def __init__(
        self,
        workflows_dir: Path,
        sources_dir: Path,
        outputs_dir: Path,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._workflows_dir: Path = workflows_dir
        self._sources_dir: Path = sources_dir
        self._outputs_dir: Path = outputs_dir
        self._environ: Mapping[str, str] = (
            environ if environ is not None else os.environ
        )

    def load(self) -> WorkflowCatalog:
        """Return every enabled workflow, source, and output definition."""
        sources: dict[str, SourceServerDefinition] = self._load_section(
            self._sources_dir, SourceServerDefinition
        )
        outputs: dict[str, OutputEndpointDefinition] = self._load_section(
            self._outputs_dir, OutputEndpointDefinition
        )
        workflows: dict[str, WorkflowDefinition] = self._load_section(
            self._workflows_dir, WorkflowDefinition
        )
        logger.info(
            "Loaded %d workflow(s), %d source(s), %d output(s)",
            len(workflows),
            len(sources),
            len(outputs),
        )
        return WorkflowCatalog(sources=sources, outputs=outputs, workflows=workflows)

    def _load_section[ModelT: BaseModel](
        self,
        directory: Path,
        model: type[ModelT],
    ) -> dict[str, ModelT]:
        if not directory.is_dir():
            logger.info("Workflow folder %s does not exist; skipping", directory)
            return {}

        loaded: dict[str, ModelT] = {}
        origins: dict[str, Path] = {}
        for path in self._iter_config_files(directory):
            document: dict[str, Any] = self._read_document(path)
            if not document.get("enabled", True):
                logger.info("Skipping disabled definition %s", path.name)
                continue
            document.setdefault("name", path.stem)
            resolved: Any = self._expand(document, path)
            try:
                definition: ModelT = model.model_validate(resolved)
            except ValidationError as err:
                raise ConfigError(path, f"invalid definition: {err}") from err

            name: str = str(getattr(definition, "name"))
            first: Path | None = origins.get(name)
            if first is not None:
                raise ConfigError(
                    path, f"duplicate name {name!r}, already defined in {first}"
                )
            origins[name] = path
            loaded[name] = definition
        return loaded

    def _iter_config_files(self, directory: Path) -> list[Path]:
        files: list[Path] = [
            path
            for path in directory.iterdir()
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
