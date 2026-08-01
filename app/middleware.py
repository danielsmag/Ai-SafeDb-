"""FastMCP middleware that enforces the per-server tool policy."""

import hashlib
import json
from collections.abc import Sequence
from typing import Any

from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult
from mcp import types as mt
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from app.connectors.models import ApiKey, ClientInfo, SessionRecord
from app.core.logging import bind_session, logger
from app.core.tracing import span, trace
from app.exceptions import (
    AuthError,
    PolicyViolationError,
    ToolBlockedError,
    ToolGuardedError,
)
from app.llm import GuardVerdict
from app.models import ToolPolicy
from app.policies.models import PiiColumn, SqlPolicy
from app.policies.sql import SqlPolicyEnforcer, SqlPolicyViolation
from app.services.guard import GuardService
from app.services.session import SessionStore


class SessionAuthMiddleware(Middleware):
    """Require a Bearer API key and recognize each MCP transport session."""

    def __init__(self, store: SessionStore, server_name: str) -> None:
        self._store: SessionStore = store
        self._server_name: str = server_name

    async def on_initialize(
        self,
        context: MiddlewareContext[mt.InitializeRequest],
        call_next: CallNext[mt.InitializeRequest, mt.InitializeResult | None],
    ) -> mt.InitializeResult | None:
        try:
            api_key: ApiKey = await self._authenticate_request()
            mcp_session_id: str = self._require_mcp_session_id(context)
            client_info: ClientInfo = self._extract_client_info(context.message)
            session: SessionRecord = await self._store.open_session(
                mcp_session_id,
                api_key,
                self._server_name,
                client_info,
            )
        except AuthError as err:
            logger.warning(
                "Session auth rejected initialize on server %r: %s",
                self._server_name,
                err.reason,
            )
            raise McpError(ErrorData(code=-32001, message=str(err))) from err

        with bind_session(
            session_id=session.id,
            mcp_session_id=session.mcp_session_id,
            api_key_name=session.api_key_name,
        ):
            logger.info(
                "Opened MCP session on server %r client=%r/%r",
                self._server_name,
                session.client_name,
                session.client_version,
            )
            return await call_next(context)

    async def on_request(
        self,
        context: MiddlewareContext[mt.Request[Any, Any]],
        call_next: CallNext[mt.Request[Any, Any], Any],
    ) -> Any:
        if context.method == "initialize":
            return await call_next(context)
        session: SessionRecord = await self._resolve_session(context)
        with bind_session(
            session_id=session.id,
            mcp_session_id=session.mcp_session_id,
            api_key_name=session.api_key_name,
        ):
            return await call_next(context)

    async def _authenticate_request(self) -> ApiKey:
        headers: dict[str, str] = get_http_headers(include={"authorization"})
        authorization: str | None = headers.get("authorization")
        if authorization is None:
            raise AuthError(self._server_name, "missing Authorization header")
        parts: list[str] = authorization.split(" ", maxsplit=1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
            raise AuthError(
                self._server_name,
                "Authorization header must be Bearer <api_key>",
            )
        raw_key: str = parts[1].strip()
        api_key: ApiKey | None = await self._store.authenticate(raw_key)
        if api_key is None:
            raise AuthError(self._server_name, "invalid or revoked API key")
        return api_key

    async def _resolve_session(
        self,
        context: MiddlewareContext[Any],
    ) -> SessionRecord:
        mcp_session_id: str = self._require_mcp_session_id(context)
        session: SessionRecord | None = await self._store.touch(mcp_session_id)
        if session is None:
            raise AuthError(
                self._server_name,
                "unknown or closed MCP session; re-initialize with a valid API key",
            )
        return session

    def _require_mcp_session_id(self, context: MiddlewareContext[Any]) -> str:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None:
            raise AuthError(self._server_name, "MCP session context unavailable")
        try:
            mcp_session_id: str = fastmcp_context.session_id
        except RuntimeError as err:
            raise AuthError(self._server_name, "MCP session id unavailable") from err
        if not mcp_session_id:
            raise AuthError(self._server_name, "empty MCP session id")
        return mcp_session_id

    @staticmethod
    def _extract_client_info(message: mt.InitializeRequest) -> ClientInfo:
        params: mt.InitializeRequestParams | None = message.params
        if params is None or params.clientInfo is None:
            return ClientInfo()
        info: mt.Implementation = params.clientInfo
        return ClientInfo(name=info.name, version=info.version)


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
