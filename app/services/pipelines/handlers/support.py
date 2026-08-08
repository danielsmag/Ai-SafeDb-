"""Shared helpers for built-in pipeline task handlers."""

from app.services.pipelines.models import (
    JsonValue,
    TaskDefinition,
    TaskResult,
    TaskType,
)


def dependency_payload(
    dependencies: dict[str, TaskResult],
) -> dict[str, JsonValue]:
    """Collect dependency outputs under their task names."""
    return {name: result.output for name, result in dependencies.items()}


def successful_result(
    task: TaskDefinition,
    output: JsonValue,
    metadata: dict[str, JsonValue] | None = None,
) -> TaskResult:
    """Build a successful task result."""
    result_metadata: dict[str, JsonValue] = metadata or {}
    return TaskResult(
        name=task.name,
        type=task.type,
        status="succeeded",
        output=output,
        metadata=result_metadata,
    )


def failed_result(
    task: TaskDefinition,
    error: str,
    output: JsonValue = None,
) -> TaskResult:
    """Build a failed task result."""
    task_type: TaskType = task.type
    return TaskResult(
        name=task.name,
        type=task_type,
        status="failed",
        output=output,
        error=error,
    )
