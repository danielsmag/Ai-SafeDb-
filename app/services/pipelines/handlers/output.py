"""Output pipeline task handler."""

from app.services.pipelines.context import ExecutionContext
from app.services.pipelines.handlers.support import (
    dependency_payload,
    successful_result,
)
from app.services.pipelines.models import (
    JsonValue,
    TaskDefinition,
    TaskResult,
    TaskType,
)


class OutputHandler:
    """Publish dependency artifacts as the pipeline's declarative output."""

    @property
    def task_type(self) -> TaskType:
        return "output"

    async def execute(
        self,
        task: TaskDefinition,
        dependencies: dict[str, TaskResult],
        context: ExecutionContext,
    ) -> TaskResult:
        output: dict[str, JsonValue] = {
            "config": dict(task.config),
            "dependencies": dependency_payload(dependencies),
        }
        return successful_result(task, output)
