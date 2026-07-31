"""FastMCP middleware that enforces the per-server tool policy."""

from collections.abc import Sequence
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult
from mcp import types as mt

from app.core.logging import logger
from app.exceptions import ToolBlockedError, ToolGuardedError
from app.llm import GuardVerdict
from app.models import ToolPolicy
from app.services.guard import GuardService


class ToolPolicyMiddleware(Middleware):
    """Hides disallowed tools from listings and rejects calls to them.

    Filtering the listing alone is not enough: a client that already knows a tool
    name could still call it, so `on_call_tool` re-checks the policy.
    """

    def __init__(self, policy: ToolPolicy, server_name: str) -> None:
        self._policy: ToolPolicy = policy
        self._server_name: str = server_name

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools: Sequence[Tool] = await call_next(context)
        permitted: list[Tool] = [
            tool for tool in tools if self._policy.permits(tool.name)
        ]
        hidden: int = len(tools) - len(permitted)
        if hidden:
            logger.debug(
                "Tool policy hid %d/%d tools for server %r",
                hidden,
                len(tools),
                self._server_name,
            )
        return permitted

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name: str = context.message.name
        arguments: dict[str, Any] | None = context.message.arguments
        logger.info(
            "Tool call on server %r: %r argument_keys=%s",
            self._server_name,
            tool_name,
            sorted(arguments) if arguments else [],
        )
        if not self._policy.permits(tool_name):
            logger.warning(
                "Blocked call to tool %r on server %r",
                tool_name,
                self._server_name,
            )
            raise ToolBlockedError(self._server_name, tool_name)
        return await call_next(context)


class LlmGuardMiddleware(Middleware):
    """Apply model-assisted safety checks around a permitted tool call."""

    def __init__(
        self,
        guard: GuardService,
        server_name: str,
        inspect_results: bool,
    ) -> None:
        self._guard: GuardService = guard
        self._server_name: str = server_name
        self._inspect_results: bool = inspect_results

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name: str = context.message.name
        arguments: dict[str, Any] | None = context.message.arguments
        call_verdict: GuardVerdict = await self._guard.review_call(
            self._server_name,
            tool_name,
            arguments,
        )
        if call_verdict.decision == "block":
            raise ToolGuardedError(
                self._server_name,
                tool_name,
                call_verdict.reason,
            )

        result: ToolResult = await call_next(context)
        if not self._inspect_results:
            return result

        result_text: str = result.model_dump_json(
            exclude={"meta"},
            fallback=lambda value: str(value),
        )
        result_verdict: GuardVerdict = await self._guard.review_result(
            self._server_name,
            tool_name,
            result_text,
        )
        if result_verdict.decision == "block":
            raise ToolGuardedError(
                self._server_name,
                tool_name,
                result_verdict.reason,
            )
        return result
