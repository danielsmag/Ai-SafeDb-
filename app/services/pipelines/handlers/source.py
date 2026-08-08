"""Source pipeline task handler."""

from app.services.pipelines.context import ExecutionContext
from app.services.pipelines.handlers.support import successful_result
from app.services.pipelines.models import (
    JsonValue,
    TaskDefinition,
    TaskResult,
    TaskType,
)


class SourceHandler:
    """Resolve an inline source or an MCP server source reference."""

    @property
    def task_type(self) -> TaskType:
        return "source"

    async def execute(
        self,
        task: TaskDefinition,
        dependencies: dict[str, TaskResult],
        context: ExecutionContext,
    ) -> TaskResult:
        reference_value: JsonValue = task.config.get("ref")
        reference: str | None = (
            reference_value if isinstance(reference_value, str) else None
        )
        if reference is not None and reference in context.mcp_servers:
            output: dict[str, JsonValue] = context.mcp_servers[
                reference
            ].source.model_dump(mode="json")
            return successful_result(task, output, {"reference": reference})
        return successful_result(task, dict(task.config))
