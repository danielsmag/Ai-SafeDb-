"""MCP server pipeline task handler."""

from app.models import McpServerConfig
from app.services.pipelines.context import ExecutionContext
from app.services.pipelines.handlers.support import failed_result, successful_result
from app.services.pipelines.models import (
    JsonValue,
    TaskDefinition,
    TaskResult,
    TaskType,
)


class McpServerHandler:
    """Resolve a configured MCP server into a pipeline artifact."""

    @property
    def task_type(self) -> TaskType:
        return "mcp_server"

    async def execute(
        self,
        task: TaskDefinition,
        dependencies: dict[str, TaskResult],
        context: ExecutionContext,
    ) -> TaskResult:
        server_value: JsonValue = task.config.get("server")
        server_name: str | None = (
            server_value if isinstance(server_value, str) else None
        )
        if server_name is None:
            return failed_result(task, "config.server must name an MCP server")
        server: McpServerConfig | None = context.mcp_servers.get(server_name)
        if server is None:
            return failed_result(task, f"unknown MCP server {server_name!r}")
        output: dict[str, JsonValue] = server.model_dump(mode="json")
        return successful_result(task, output, {"server": server_name})
