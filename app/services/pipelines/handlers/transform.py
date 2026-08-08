"""Transform pipeline task handler."""

from app.services.pipelines.context import ExecutionContext
from app.services.pipelines.handlers.support import (
    dependency_payload,
    failed_result,
    successful_result,
)
from app.services.pipelines.models import (
    JsonValue,
    TaskDefinition,
    TaskResult,
    TaskType,
)


class TransformHandler:
    """Apply safe built-in transformations to dependency outputs."""

    @property
    def task_type(self) -> TaskType:
        return "transform"

    async def execute(
        self,
        task: TaskDefinition,
        dependencies: dict[str, TaskResult],
        context: ExecutionContext,
    ) -> TaskResult:
        operation_value: JsonValue = task.config.get("operation", "merge")
        operation: str | None = (
            operation_value if isinstance(operation_value, str) else None
        )
        payload: dict[str, JsonValue] = dependency_payload(dependencies)
        if operation == "merge":
            merged: dict[str, JsonValue] = {}
            for output in payload.values():
                if isinstance(output, dict):
                    merged.update(output)
            merged.update(
                {key: value for key, value in task.config.items() if key != "operation"}
            )
            return successful_result(task, merged, {"operation": "merge"})
        if operation == "collect":
            return successful_result(task, payload, {"operation": "collect"})
        return failed_result(task, f"unsupported transform operation {operation!r}")
