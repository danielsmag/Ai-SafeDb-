"""Policy pipeline task handler."""

from app.policies import Policy
from app.services.pipelines.context import ExecutionContext
from app.services.pipelines.handlers.support import failed_result, successful_result
from app.services.pipelines.models import (
    JsonValue,
    TaskDefinition,
    TaskResult,
    TaskType,
)


class PolicyHandler:
    """Resolve a named policy and expose its validated configuration."""

    @property
    def task_type(self) -> TaskType:
        return "policy"

    async def execute(
        self,
        task: TaskDefinition,
        dependencies: dict[str, TaskResult],
        context: ExecutionContext,
    ) -> TaskResult:
        policy_value: JsonValue = task.config.get("policy")
        policy_name: str | None = (
            policy_value if isinstance(policy_value, str) else None
        )
        if policy_name is None:
            return failed_result(task, "config.policy must name a configured policy")
        policy: Policy | None = context.policies.get(policy_name)
        if policy is None:
            return failed_result(task, f"unknown policy {policy_name!r}")
        output: dict[str, JsonValue] = policy.model_dump(mode="json")
        return successful_result(task, output, {"policy": policy_name})
