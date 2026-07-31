"""FastMCP middleware that enforces the per-server tool policy."""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult
from mcp import types as mt

from app.core.logging import logger
from app.core.tracing import span, trace
from app.exceptions import PolicyViolationError, ToolBlockedError, ToolGuardedError
from app.llm import GuardVerdict
from app.models import ToolPolicy
from app.policies.models import PiiColumn, SqlPolicy
from app.policies.sql import SqlPolicyEnforcer, SqlPolicyViolation
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
        with trace("tool_call", server=self._server_name, tool=tool_name):
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


class SqlPolicyMiddleware(Middleware):
    """Reject SQL calls that violate deterministic access rules."""

    def __init__(self, policy: SqlPolicy, server_name: str) -> None:
        self._enforcer: SqlPolicyEnforcer = SqlPolicyEnforcer(policy)
        self._server_name: str = server_name

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name: str = context.message.name
        arguments: dict[str, Any] | None = context.message.arguments
        statements: list[str] = self._enforcer.extract_sql(tool_name, arguments)
        try:
            for statement in statements:
                self._enforcer.enforce(statement)
        except SqlPolicyViolation as err:
            logger.warning(
                "SQL policy blocked tool %r on server %r: %s",
                tool_name,
                self._server_name,
                err,
            )
            raise PolicyViolationError(
                self._server_name,
                tool_name,
                str(err),
            ) from err
        return await call_next(context)


class PiiMaskingMiddleware(Middleware):
    """Redact policy-declared PII fields from structured and JSON results."""

    def __init__(self, policy: SqlPolicy) -> None:
        enforcer: SqlPolicyEnforcer = SqlPolicyEnforcer(policy)
        self._rules: dict[str, PiiColumn] = enforcer.result_pii_rules()

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        result: ToolResult = await call_next(context)
        if not self._rules:
            return result

        structured_content: dict[str, Any] | None = result.structured_content
        masked_structured: dict[str, Any] | None = (
            self._mask_value(structured_content)
            if structured_content is not None
            else None
        )
        content: list[mt.ContentBlock] = [
            self._mask_content(block) for block in result.content
        ]
        return result.model_copy(
            update={
                "content": content,
                "structured_content": masked_structured,
            }
        )

    def _mask_content(self, block: mt.ContentBlock) -> mt.ContentBlock:
        if not isinstance(block, mt.TextContent):
            return block
        try:
            value: object = json.loads(block.text)
        except json.JSONDecodeError, TypeError:
            return block
        masked: object = self._mask_value(value)
        return block.model_copy(
            update={"text": json.dumps(masked, separators=(",", ":"), default=str)}
        )

    def _mask_value(self, value: object) -> Any:
        if isinstance(value, dict):
            masked_mapping: dict[str, Any] = {}
            for key, item in value.items():
                rule: PiiColumn | None = self._rules.get(str(key).lower())
                masked_mapping[str(key)] = (
                    self._transform(item, rule)
                    if rule is not None
                    else self._mask_value(item)
                )
            return masked_mapping
        if isinstance(value, list):
            return [self._mask_value(item) for item in value]
        return value

    @staticmethod
    def _transform(value: object, rule: PiiColumn) -> object:
        if value is None or rule.action == "block":
            return value
        text: str = str(value)
        if rule.action == "hash":
            digest: str = hashlib.sha256(text.encode("utf-8")).hexdigest()
            return f"sha256:{digest[:16]}"
        if "@" in text:
            local: str
            domain: str
            local, domain = text.split("@", maxsplit=1)
            prefix: str = local[:1]
            return f"{prefix}***@{domain}"
        if len(text) <= 4:
            return "***"
        return f"{text[:1]}***{text[-1:]}"


class LlmGuardMiddleware(Middleware):
    """Apply model-assisted safety checks around a permitted tool call."""

    def __init__(
        self,
        guard: GuardService,
        server_name: str,
        inspect_results: bool,
        policy: SqlPolicy | None = None,
    ) -> None:
        self._guard: GuardService = guard
        self._server_name: str = server_name
        self._inspect_results: bool = inspect_results
        self._policy_context: str | None = (
            policy.model_dump_json(exclude={"denied_keywords"})
            if policy is not None
            else None
        )

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name: str = context.message.name
        arguments: dict[str, Any] | None = context.message.arguments
        with span("guard.review_call", server=self._server_name, tool=tool_name):
            call_verdict: GuardVerdict = await self._guard.review_call(
                self._server_name,
                tool_name,
                arguments,
                self._policy_context,
            )
        if call_verdict.decision == "block":
            raise ToolGuardedError(
                self._server_name,
                tool_name,
                call_verdict.reason,
            )

        with span("tool.execute", server=self._server_name, tool=tool_name):
            result: ToolResult = await call_next(context)
        if not self._inspect_results:
            return result

        result_text: str = result.model_dump_json(
            exclude={"meta"},
            fallback=lambda value: str(value),
        )
        with span("guard.review_result", server=self._server_name, tool=tool_name):
            result_verdict: GuardVerdict = await self._guard.review_result(
                self._server_name,
                tool_name,
                result_text,
                self._policy_context,
            )
        if result_verdict.decision == "block":
            raise ToolGuardedError(
                self._server_name,
                tool_name,
                result_verdict.reason,
            )
        return result
