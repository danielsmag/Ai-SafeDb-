"""FastMCP middleware that enforces the per-server tool policy."""

import logging
from collections.abc import Sequence

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult
from mcp import types as mt

from app.exceptions import ToolBlockedError
from app.models import ToolPolicy

logger = logging.getLogger(__name__)


class ToolPolicyMiddleware(Middleware):
    """Hides disallowed tools from listings and rejects calls to them.

    Filtering the listing alone is not enough: a client that already knows a tool
    name could still call it, so `on_call_tool` re-checks the policy.
    """

    def __init__(self, policy: ToolPolicy, server_name: str) -> None:
        self._policy = policy
        self._server_name = server_name

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next: CallNext[mt.ListToolsRequest, Sequence[Tool]],
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        permitted = [tool for tool in tools if self._policy.permits(tool.name)]
        hidden = len(tools) - len(permitted)
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
        tool_name = context.message.name
        if not self._policy.permits(tool_name):
            logger.warning(
                "Blocked call to tool %r on server %r",
                tool_name,
                self._server_name,
            )
            raise ToolBlockedError(self._server_name, tool_name)
        return await call_next(context)
