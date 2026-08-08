"""Shared runtime context passed to pipeline task handlers."""

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field

from app.models import McpServerConfig
from app.policies import Policy
from app.services.guard import GuardService
from app.services.pipelines.models import JsonValue, TaskResult


class ExecutionContext(BaseModel):
    """Pipeline inputs, resolved resources, and completed task outputs."""

    model_config: ClassVar[ConfigDict] = ConfigDict(arbitrary_types_allowed=True)

    inputs: dict[str, JsonValue] = Field(default_factory=dict)
    task_results: dict[str, TaskResult] = Field(default_factory=dict)
    mcp_servers: dict[str, McpServerConfig] = Field(default_factory=dict)
    policies: dict[str, Policy] = Field(default_factory=dict)
    guard_service: GuardService | None = None

    def dependency_outputs(self, task: str) -> dict[str, JsonValue]:
        """Return successful direct dependency outputs for a task result."""
        result: TaskResult | None = self.task_results.get(task)
        if result is None or not isinstance(result.output, dict):
            return {}
        return result.output
