"""LLM guard pipeline task handler."""

from app.llm import GuardVerdict
from app.services.guard import GuardService
from app.services.pipelines.context import ExecutionContext
from app.services.pipelines.handlers.support import failed_result, successful_result
from app.services.pipelines.models import (
    JsonValue,
    TaskDefinition,
    TaskResult,
    TaskType,
)


class GuardHandler:
    """Run the configured guard when call data is supplied."""

    @property
    def task_type(self) -> TaskType:
        return "guard"

    async def execute(
        self,
        task: TaskDefinition,
        dependencies: dict[str, TaskResult],
        context: ExecutionContext,
    ) -> TaskResult:
        tool_value: JsonValue = task.config.get("tool_name")
        arguments_value: JsonValue = task.config.get("arguments")
        if not isinstance(tool_value, str) or not isinstance(arguments_value, dict):
            return successful_result(
                task,
                {
                    "configured": True,
                    "inspect_results": task.config.get("inspect_results", True),
                },
                {"mode": "configuration"},
            )

        guard: GuardService | None = context.guard_service
        if guard is None:
            return failed_result(task, "guard service is unavailable")
        server_value: JsonValue = task.config.get(
            "server", context.inputs.get("server")
        )
        server_name: str = server_value if isinstance(server_value, str) else "pipeline"
        arguments: dict[str, object] = dict(arguments_value)
        verdict: GuardVerdict = await guard.review_call(
            server_name=server_name,
            tool_name=tool_value,
            arguments=arguments,
        )
        output: dict[str, JsonValue] = verdict.model_dump(mode="json")
        if verdict.decision == "block":
            return failed_result(task, verdict.reason, output)
        return successful_result(task, output, {"mode": "call"})
