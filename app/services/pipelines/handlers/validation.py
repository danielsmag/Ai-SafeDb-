"""Validation pipeline task handler."""

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


class ValidationHandler:
    """Validate dependency success and optional required output keys."""

    @property
    def task_type(self) -> TaskType:
        return "validation"

    async def execute(
        self,
        task: TaskDefinition,
        dependencies: dict[str, TaskResult],
        context: ExecutionContext,
    ) -> TaskResult:
        failed_dependencies: list[str] = [
            name
            for name, result in dependencies.items()
            if result.status not in {"succeeded", "skipped"}
        ]
        if failed_dependencies:
            return failed_result(
                task,
                "failed dependencies: " + ", ".join(sorted(failed_dependencies)),
            )

        required_value: JsonValue = task.config.get("required_keys", [])
        required_keys: list[str] = (
            [value for value in required_value if isinstance(value, str)]
            if isinstance(required_value, list)
            else []
        )
        payload: dict[str, JsonValue] = dependency_payload(dependencies)
        available_keys: set[str] = {
            key
            for output in payload.values()
            if isinstance(output, dict)
            for key in output
        }
        missing: list[str] = sorted(set(required_keys) - available_keys)
        if missing:
            return failed_result(
                task, "required output keys missing: " + ", ".join(missing)
            )
        return successful_result(
            task,
            {"valid": True, "dependencies": payload},
            {"checks": len(required_keys) + 1},
        )
