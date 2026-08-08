"""Task handler contract and shared handler utilities."""

from typing import Protocol

from app.services.pipelines.context import ExecutionContext
from app.services.pipelines.models import TaskDefinition, TaskResult, TaskType


class TaskHandler(Protocol):
    """Strategy used to execute one pipeline task type."""

    @property
    def task_type(self) -> TaskType:
        """Task type handled by this strategy."""
        ...

    async def execute(
        self,
        task: TaskDefinition,
        dependencies: dict[str, TaskResult],
        context: ExecutionContext,
    ) -> TaskResult:
        """Execute one task using its dependency results."""
        ...
