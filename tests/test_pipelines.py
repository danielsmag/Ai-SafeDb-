"""Tests for declarative pipeline loading, validation, and execution."""

from pathlib import Path

import pytest
from pydantic import ValidationError

from app.exceptions import ConfigError
from app.models import McpServerConfig
from app.policies import SqlPolicy
from app.services.pipelines import (
    ExecutionContext,
    HandlerRegistry,
    PipelineCatalog,
    PipelineDefinition,
    PipelineExecutor,
    PipelineLoader,
    PipelineResult,
)
from app.services.pipelines.handlers import (
    McpServerHandler,
    OutputHandler,
    PolicyHandler,
    SourceHandler,
    TransformHandler,
    ValidationHandler,
)


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


def _registry() -> HandlerRegistry:
    return HandlerRegistry(
        handlers=[
            SourceHandler(),
            PolicyHandler(),
            TransformHandler(),
            ValidationHandler(),
            McpServerHandler(),
            OutputHandler(),
        ]
    )


def test_definition_rejects_missing_dependency() -> None:
    with pytest.raises(ValidationError, match="unknown dependencies"):
        PipelineDefinition.model_validate(
            {
                "name": "broken",
                "tasks": [
                    {
                        "name": "publish",
                        "type": "output",
                        "depends_on": ["missing"],
                    }
                ],
            }
        )


def test_definition_rejects_cycle() -> None:
    with pytest.raises(ValidationError, match="dependency cycle"):
        PipelineDefinition.model_validate(
            {
                "name": "cyclic",
                "tasks": [
                    {"name": "one", "type": "source", "depends_on": ["two"]},
                    {"name": "two", "type": "output", "depends_on": ["one"]},
                ],
            }
        )


def test_loader_expands_environment_and_skips_disabled(tmp_path: Path) -> None:
    pipelines_dir: Path = tmp_path / "pipelines"
    pipelines_dir.mkdir()
    _write(
        pipelines_dir / "enabled.yaml",
        (
            "name: enabled\n"
            "tasks:\n"
            "  - name: source\n"
            "    type: source\n"
            "    config:\n"
            "      host: ${HOST}\n"
        ),
    )
    _write(
        pipelines_dir / "disabled.yaml",
        "name: disabled\nenabled: false\ntasks: invalid\n",
    )

    loader: PipelineLoader = PipelineLoader(
        pipelines_dir,
        environ={"HOST": "database.internal"},
    )
    catalog: PipelineCatalog = loader.load()

    assert set(catalog.pipelines) == {"enabled"}
    assert catalog.pipelines["enabled"].tasks[0].config["host"] == "database.internal"


def test_loader_wraps_invalid_dag_with_path(tmp_path: Path) -> None:
    pipelines_dir: Path = tmp_path / "pipelines"
    pipelines_dir.mkdir()
    path: Path = pipelines_dir / "bad.yaml"
    _write(
        path,
        (
            "name: bad\n"
            "tasks:\n"
            "  - name: output\n"
            "    type: output\n"
            "    depends_on: [unknown]\n"
        ),
    )

    with pytest.raises(ConfigError, match=str(path)):
        PipelineLoader(pipelines_dir).load()


async def test_executor_runs_dependency_dag() -> None:
    pipeline: PipelineDefinition = PipelineDefinition.model_validate(
        {
            "name": "postgres-pipeline",
            "tasks": [
                {"name": "source", "type": "source", "config": {"ref": "postgres"}},
                {
                    "name": "policy",
                    "type": "policy",
                    "depends_on": ["source"],
                    "config": {"policy": "readonly"},
                },
                {
                    "name": "collect",
                    "type": "transform",
                    "depends_on": ["source", "policy"],
                    "config": {"operation": "collect"},
                },
                {
                    "name": "validate",
                    "type": "validation",
                    "depends_on": ["collect"],
                },
                {
                    "name": "server",
                    "type": "mcp_server",
                    "depends_on": ["validate"],
                    "config": {"server": "postgres"},
                },
                {
                    "name": "output",
                    "type": "output",
                    "depends_on": ["server"],
                    "config": {"transport": "http"},
                },
            ],
        }
    )
    server: McpServerConfig = McpServerConfig.model_validate(
        {
            "name": "postgres",
            "source": {"transport": "stdio", "command": "npx"},
        }
    )
    policy: SqlPolicy = SqlPolicy.model_validate({"name": "readonly", "type": "sql"})
    context: ExecutionContext = ExecutionContext(
        mcp_servers={"postgres": server},
        policies={"readonly": policy},
    )
    executor: PipelineExecutor = PipelineExecutor(_registry())

    result: PipelineResult = await executor.execute(pipeline, context)

    assert result.status == "succeeded"
    assert all(task.status == "succeeded" for task in result.tasks.values())
    assert result.tasks["output"].output is not None


async def test_executor_honors_skip_failure_mode() -> None:
    pipeline: PipelineDefinition = PipelineDefinition.model_validate(
        {
            "name": "skip-failure",
            "tasks": [
                {
                    "name": "unknown-policy",
                    "type": "policy",
                    "on_failure": "skip",
                    "config": {"policy": "missing"},
                },
                {
                    "name": "output",
                    "type": "output",
                    "depends_on": ["unknown-policy"],
                },
            ],
        }
    )
    executor: PipelineExecutor = PipelineExecutor(_registry())

    result: PipelineResult = await executor.execute(pipeline, ExecutionContext())

    assert result.status == "succeeded"
    assert result.tasks["unknown-policy"].status == "skipped"
    assert result.tasks["output"].status == "succeeded"
