"""Validated models for declarative pipeline DAGs and their executions."""

from datetime import UTC, datetime
from typing import ClassVar, Literal, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.models import SERVER_NAME_PATTERN

type JsonValue = (
    str | int | float | bool | None | dict[str, "JsonValue"] | list["JsonValue"]
)
type TaskType = Literal[
    "source",
    "policy",
    "transform",
    "validation",
    "guard",
    "mcp_server",
    "output",
    "custom",
]
type FailureMode = Literal["fail", "skip", "warn"]
type TaskStatus = Literal[
    "pending", "running", "succeeded", "failed", "skipped", "cancelled"
]
type PipelineStatus = Literal["pending", "running", "succeeded", "failed", "cancelled"]


class TaskDefinition(BaseModel):
    """One executable node in a pipeline DAG."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=SERVER_NAME_PATTERN, max_length=64)
    type: TaskType
    depends_on: list[str] = Field(default_factory=list)
    config: dict[str, JsonValue] = Field(default_factory=dict)
    enabled: bool = True
    on_failure: FailureMode = "fail"


class PipelineDefinition(BaseModel):
    """One YAML pipeline with an acyclic task dependency graph."""

    model_config: ClassVar[ConfigDict] = ConfigDict(extra="forbid", frozen=True)

    name: str = Field(pattern=SERVER_NAME_PATTERN, max_length=64)
    enabled: bool = True
    description: str | None = None
    tasks: list[TaskDefinition] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_dag(self) -> Self:
        task_names: list[str] = [task.name for task in self.tasks]
        unique_names: set[str] = set(task_names)
        if len(unique_names) != len(task_names):
            duplicate: str = next(
                name for name in task_names if task_names.count(name) > 1
            )
            raise ValueError(f"duplicate task name {duplicate!r}")

        for task in self.tasks:
            missing: list[str] = [
                dependency
                for dependency in task.depends_on
                if dependency not in unique_names
            ]
            if missing:
                raise ValueError(
                    f"task {task.name!r} has unknown dependencies: "
                    + ", ".join(sorted(missing))
                )
            if task.name in task.depends_on:
                raise ValueError(f"task {task.name!r} cannot depend on itself")

        self._assert_acyclic()
        return self

    def _assert_acyclic(self) -> None:
        remaining: dict[str, set[str]] = {
            task.name: set(task.depends_on) for task in self.tasks
        }
        ready: list[str] = sorted(
            name for name, dependencies in remaining.items() if not dependencies
        )
        visited: int = 0
        while ready:
            completed: str = ready.pop(0)
            visited += 1
            for name, dependencies in remaining.items():
                if completed not in dependencies:
                    continue
                dependencies.remove(completed)
                if not dependencies:
                    ready.append(name)
                    ready.sort()
        if visited != len(remaining):
            cyclic: list[str] = sorted(
                name for name, dependencies in remaining.items() if dependencies
            )
            raise ValueError(
                "pipeline contains a dependency cycle involving: " + ", ".join(cyclic)
            )


class PipelineCatalog(BaseModel):
    """All enabled pipeline definitions loaded at startup."""

    pipelines: dict[str, PipelineDefinition] = Field(default_factory=dict)


class TaskResult(BaseModel):
    """Execution result for one task node."""

    name: str
    type: TaskType
    status: TaskStatus = "pending"
    output: JsonValue = None
    error: str | None = None
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
    started_at: datetime | None = None
    finished_at: datetime | None = None


class PipelineResult(BaseModel):
    """Snapshot of one pipeline execution."""

    run_id: UUID
    pipeline_name: str
    status: PipelineStatus = "pending"
    tasks: dict[str, TaskResult] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    finished_at: datetime | None = None
    error: str | None = None


class PipelineNodeResponse(BaseModel):
    """One pipeline task rendered as a DAG node."""

    id: str
    kind: TaskType
    label: str
    enabled: bool
    on_failure: FailureMode
    details: dict[str, str]
    yaml: str


class PipelineEdgeResponse(BaseModel):
    """Directed dependency edge between two pipeline tasks."""

    from_id: str
    to_id: str


class PipelineGraphResponse(BaseModel):
    """Renderable pipeline graph."""

    nodes: list[PipelineNodeResponse]
    edges: list[PipelineEdgeResponse]


class PipelineSummaryResponse(BaseModel):
    """Pipeline definition, graph, and latest execution state."""

    name: str
    enabled: bool
    description: str | None
    task_count: int
    graph: PipelineGraphResponse
    latest_run: PipelineResult | None = None


class PipelineListResponse(BaseModel):
    """Admin response containing every configured pipeline."""

    pipelines: list[PipelineSummaryResponse]


class PipelineRunRequest(BaseModel):
    """Optional user-provided values for a pipeline execution."""

    inputs: dict[str, JsonValue] = Field(default_factory=dict)
