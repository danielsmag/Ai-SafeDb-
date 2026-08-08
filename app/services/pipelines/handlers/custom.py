"""Default custom pipeline task handler."""

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


class CustomHandler:
    """Expose custom task configuration without loading code from YAML."""

    @property
    def task_type(self) -> TaskType:
        return "custom"

    async def execute(
        self,
        task: TaskDefinition,
        dependencies: dict[str, TaskResult],
        context: ExecutionContext,
    ) -> TaskResult:
        output: dict[str, JsonValue] = {
            "config": dict(task.config),
            "dependencies": dependency_payload(dependencies),
            "inputs": dict(context.inputs),
        }
        return successful_result(task, output)
