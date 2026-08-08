"""Load declarative pipeline DAGs from YAML files."""

import os
import re
from collections.abc import Mapping
from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.logging import logger
from app.exceptions import ConfigError, MissingEnvVarError
from app.services.pipelines.models import JsonValue, PipelineCatalog, PipelineDefinition

_YAML_SUFFIXES: tuple[str, str] = (".yaml", ".yml")
_ENV_PLACEHOLDER: re.Pattern[str] = re.compile(
    r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}"
)


class PipelineLoader:
    """Read, expand, and validate pipeline YAML definitions."""

    def __init__(
        self,
        pipelines_dir: Path,
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self._pipelines_dir: Path = pipelines_dir
        self._environ: Mapping[str, str] = (
            environ if environ is not None else os.environ
        )

    @property
    def pipelines_dir(self) -> Path:
        return self._pipelines_dir

    def load(self) -> PipelineCatalog:
        """Return every enabled, valid pipeline."""
        if not self._pipelines_dir.is_dir():
            logger.info(
                "Pipeline folder %s does not exist; skipping", self._pipelines_dir
            )
            return PipelineCatalog()

        pipelines: dict[str, PipelineDefinition] = {}
        origins: dict[str, Path] = {}
        for path in self._iter_config_files():
            document: dict[str, JsonValue] = self._read_document(path)
            if document.get("enabled", True) is False:
                logger.info("Skipping disabled pipeline %s", path.name)
                continue
            document.setdefault("name", path.stem)
            resolved: JsonValue = self._expand(document, path)
            try:
                pipeline: PipelineDefinition = PipelineDefinition.model_validate(
                    resolved
                )
            except ValidationError as error:
                raise ConfigError(path, f"invalid pipeline: {error}") from error
            first: Path | None = origins.get(pipeline.name)
            if first is not None:
                raise ConfigError(
                    path,
                    f"duplicate pipeline name {pipeline.name!r}, "
                    f"already defined in {first}",
                )
            origins[pipeline.name] = path
            pipelines[pipeline.name] = pipeline
        logger.info("Loaded %d pipeline(s)", len(pipelines))
        return PipelineCatalog(pipelines=pipelines)

    def _iter_config_files(self) -> list[Path]:
        files: list[Path] = [
            path
            for path in self._pipelines_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in _YAML_SUFFIXES
            and not path.name.startswith(".")
        ]
        return sorted(files)

    def _read_document(self, path: Path) -> dict[str, JsonValue]:
        try:
            raw: str = path.read_text(encoding="utf-8")
        except OSError as error:
            raise ConfigError(path, f"cannot read file: {error}") from error
        try:
            document: object = yaml.safe_load(raw)
        except yaml.YAMLError as error:
            raise ConfigError(path, f"invalid YAML: {error}") from error
        if document is None:
            raise ConfigError(path, "file is empty")
        if not isinstance(document, dict):
            raise ConfigError(path, "top-level YAML value must be a mapping")
        return document

    def _expand(self, value: JsonValue, path: Path) -> JsonValue:
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
