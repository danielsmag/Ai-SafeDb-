"""FastMCP middleware that enforces the per-server tool policy."""

import json
from collections.abc import Sequence
from typing import Any, Final

from fastmcp.server.dependencies import get_http_headers
from fastmcp.server.middleware import CallNext, Middleware, MiddlewareContext
from fastmcp.tools import Tool, ToolResult
from mcp import types as mt
from mcp.shared.exceptions import McpError
from mcp.types import ErrorData

from app.connectors.models import ApiKey, ClientInfo, SessionRecord
from app.core.config import GuardErrorMode
from app.core.logging import bind_session, logger
from app.core.tracing import span, trace
from app.exceptions import (
    AuthError,
    LlmUnavailableError,
    PolicyViolationError,
    ToolBlockedError,
    ToolGuardedError,
)
from app.llm import GuardVerdict
from app.models import ToolPolicy
from app.policies.models import PiiColumn, SqlDialect, SqlPolicy
from app.policies.sql import SqlPolicyEnforcer, SqlPolicyViolation
from app.reporting import (
    REPORT_META_KEY,
    ToolCallReport,
    get_report,
    start_report,
)
from app.services.guard import GuardService
from app.services.rewriter import DATA_KEY_PLACEHOLDER, PiiQueryRewriter
from app.services.session import SessionStore

PII_HASHED_IN_QUERY_STATE_KEY: Final[str] = "pii_hashed_in_query"
PII_HASHED_COLUMNS_STATE_KEY: Final[str] = "pii_hashed_columns"


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


class ToolReportMiddleware(Middleware):
    """Collect what the gateway did to a call and attach it to the result."""

    def __init__(self, server_name: str) -> None:
        self._server_name: str = server_name

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        report: ToolCallReport | None = await start_report(
            context,
            self._server_name,
            context.message.name,
        )
        result: ToolResult = await call_next(context)
        if report is None:
            return result
        meta: dict[str, Any] = dict(result.meta or {})
        meta[REPORT_META_KEY] = report.model_dump(mode="json")
        summary: str = report.summary()
        logger.info("Tool report: %s", summary)
        content: list[mt.ContentBlock] = [
            *result.content,
            mt.TextContent(type="text", text=summary),
        ]
        return result.model_copy(update={"content": content, "meta": meta})


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


class PiiHashRewriteMiddleware(Middleware):
    """Expand stars, drop PII columns, then keyed-hash mask columns in SQL."""

    def __init__(
        self,
        rewriter: PiiQueryRewriter,
        policy: SqlPolicy,
        store: SessionStore,
        server_name: str,
        on_error: GuardErrorMode,
    ) -> None:
        self._rewriter: PiiQueryRewriter = rewriter
        self._enforcer: SqlPolicyEnforcer = SqlPolicyEnforcer(policy)
        self._dialect: SqlDialect = policy.dialect
        self._store: SessionStore = store
        self._server_name: str = server_name
        self._on_error: GuardErrorMode = on_error

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
    ) -> ToolResult:
        tool_name: str = context.message.name
        arguments: dict[str, Any] | None = context.message.arguments
        sql_by_key: dict[str, str] = self._enforcer.extract_sql_arguments(
            tool_name,
            arguments,
        )
        if not sql_by_key:
            return await call_next(context)

        report: ToolCallReport | None = await get_report(context)
        prepared_by_key: dict[str, str] = {}
        mask_by_key: dict[str, dict[str, list[str]]] = {}
        for key, sql in sql_by_key.items():
            prepared: str = self._prepare_sql(tool_name, sql, report)
            mask_columns: dict[str, list[str]] = self._enforcer.hashable_pii_columns(
                prepared
            )
            if prepared != sql or mask_columns:
                prepared_by_key[key] = prepared
            if mask_columns:
                mask_by_key[key] = mask_columns

        if not prepared_by_key:
            if report is not None:
                report.executed_sql = list[str](sql_by_key.values())
            return await call_next(context)

        needs_session: bool = bool(mask_by_key)
        session: SessionRecord | None = None
        if needs_session:
            session = await self._resolve_session(context)
            if session is None:
                return await self._on_rewrite_failure(
                    tool_name,
                    "MCP session unavailable for data_key substitution",
                    context,
                    call_next,
                    prepared_by_key=prepared_by_key,
                    arguments=arguments,
                )

        hashed_columns: set[str] = set()
        executed_sql: list[str] = []
        updated_arguments: dict[str, Any] = dict(arguments or {})
        for key, prepared in prepared_by_key.items():
            mask_columns = mask_by_key.get(key, {})
            if not mask_columns:
                updated_arguments[key] = prepared
                executed_sql.append(prepared)
                continue
            assert session is not None
            rewritten: str | None = await self._rewrite_one(
                tool_name,
                prepared,
                mask_columns,
            )
            if rewritten is None:
                updated_arguments[key] = prepared
                executed_sql.append(prepared)
                continue
            updated_arguments[key] = self._substitute_data_key(
                rewritten,
                session.data_key,
            )
            executed_sql.append(rewritten)
            hashed_columns.update(
                column for columns in mask_columns.values() for column in columns
            )
            logger.info(
                "Rewrote SQL for tool %r on server %r (placeholder form):\n%s",
                tool_name,
                self._server_name,
                rewritten,
            )

        if report is not None:
            report.executed_sql = executed_sql
            report.hashed_columns = sorted(hashed_columns)

        if hashed_columns:
            await self._record_hashed_columns(context, hashed_columns)
        elif any(prepared_by_key[key] != sql_by_key[key] for key in prepared_by_key):
            logger.info(
                "Applied deterministic PII transforms for tool %r on server %r",
                tool_name,
                self._server_name,
            )

        updated_message: mt.CallToolRequestParams = context.message.model_copy(
            update={"arguments": updated_arguments}
        )
        return await call_next(context.copy(message=updated_message))

    def _prepare_sql(
        self,
        tool_name: str,
        sql: str,
        report: ToolCallReport | None,
    ) -> str:
        """Expand stars and drop drop-action columns; re-enforce after each step."""
        current: str = sql
        expanded: str | None = self._enforcer.expand_stars(current)
        if expanded is not None:
            self._enforce_or_raise(tool_name, expanded)
            current = expanded
            if report is not None:
                report.expanded_stars = True
            logger.debug(
                "Expanded SELECT * for tool %r on server %r",
                tool_name,
                self._server_name,
            )

        droppable: dict[str, list[str]] = self._enforcer.droppable_pii_columns(current)
        drop_names: set[str] = {
            column for columns in droppable.values() for column in columns
        }
        if drop_names:
            dropped: str = self._enforcer.drop_columns(current, drop_names)
            self._enforce_or_raise(tool_name, dropped)
            current = dropped
            if report is not None:
                report.dropped_columns = sorted(
                    set(report.dropped_columns) | drop_names
                )
            logger.debug(
                "Dropped PII columns %s for tool %r on server %r",
                sorted(drop_names),
                tool_name,
                self._server_name,
            )
        return current

    def _enforce_or_raise(self, tool_name: str, sql: str) -> None:
        try:
            self._enforcer.enforce(sql)
        except SqlPolicyViolation as err:
            raise PolicyViolationError(
                self._server_name,
                tool_name,
                str(err),
            ) from err

    async def _rewrite_one(
        self,
        tool_name: str,
        sql: str,
        pii_columns: dict[str, list[str]],
    ) -> str | None:
        try:
            with span("pii.rewrite_sql", server=self._server_name, tool=tool_name):
                rewritten: str | None = await self._rewriter.rewrite(
                    sql,
                    self._dialect,
                    pii_columns,
                )
        except LlmUnavailableError as err:
            if self._on_error == "allow":
                logger.warning(
                    "PII rewrite unavailable for tool %r on server %r; "
                    "forwarding prepared SQL",
                    tool_name,
                    self._server_name,
                )
                return None
            raise PolicyViolationError(
                self._server_name,
                tool_name,
                str(err),
            ) from err

        if rewritten is None:
            return None

        try:
            self._enforcer.enforce(rewritten)
        except SqlPolicyViolation as err:
            logger.warning(
                "Rewritten SQL failed policy for tool %r on server %r: %s",
                tool_name,
                self._server_name,
                err,
            )
            if self._on_error == "allow":
                return None
            raise PolicyViolationError(
                self._server_name,
                tool_name,
                f"rewritten SQL rejected: {err}",
            ) from err
        return rewritten

    async def _resolve_session(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> SessionRecord | None:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None:
            return None
        try:
            mcp_session_id: str = fastmcp_context.session_id
        except RuntimeError:
            return None
        if not mcp_session_id:
            return None
        return await self._store.get_session(mcp_session_id)

    async def _on_rewrite_failure(
        self,
        tool_name: str,
        reason: str,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next: CallNext[mt.CallToolRequestParams, ToolResult],
        *,
        prepared_by_key: dict[str, str],
        arguments: dict[str, Any] | None,
    ) -> ToolResult:
        if self._on_error == "allow":
            logger.warning(
                "PII rewrite skipped for tool %r on server %r: %s",
                tool_name,
                self._server_name,
                reason,
            )
            updated_arguments: dict[str, Any] = dict(arguments or {})
            updated_arguments.update(prepared_by_key)
            updated_message: mt.CallToolRequestParams = context.message.model_copy(
                update={"arguments": updated_arguments}
            )
            return await call_next(context.copy(message=updated_message))
        raise PolicyViolationError(self._server_name, tool_name, reason)

    @staticmethod
    async def _record_hashed_columns(
        context: MiddlewareContext[mt.CallToolRequestParams],
        columns: set[str],
    ) -> None:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None:
            return
        # Request-scoped: serializable state outlives the call and would make a
        # later query look already hashed.
        await fastmcp_context.set_state(
            PII_HASHED_IN_QUERY_STATE_KEY,
            True,
            serializable=False,
        )
        await fastmcp_context.set_state(
            PII_HASHED_COLUMNS_STATE_KEY,
            sorted(columns),
            serializable=False,
        )

    @staticmethod
    def _substitute_data_key(sql: str, data_key: str) -> str:
        escaped_key: str = data_key.replace("'", "''")
        return sql.replace(DATA_KEY_PLACEHOLDER, escaped_key)


class _MaskTally:
    """Result field names changed or removed while masking one tool result."""

    def __init__(self) -> None:
        self.masked: set[str] = set()
        self.removed: set[str] = set()


class PiiMaskingMiddleware(Middleware):
    """Fallback result-side drop/mask when in-query hashing did not run."""

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
        hashed_in_query: bool = await self._was_hashed_in_query(context)
        tally: _MaskTally = _MaskTally()

        structured_content: dict[str, Any] | None = result.structured_content
        masked_structured: dict[str, Any] | None = (
            self._mask_value(
                structured_content,
                hashed_in_query=hashed_in_query,
                tally=tally,
            )
            if structured_content is not None
            else None
        )
        content: list[mt.ContentBlock] = [
            self._mask_content(block, hashed_in_query=hashed_in_query, tally=tally)
            for block in result.content
        ]
        report: ToolCallReport | None = await get_report(context)
        if report is not None:
            report.masked_fields = sorted(tally.masked)
            report.removed_fields = sorted(tally.removed)
        return result.model_copy(
            update={
                "content": content,
                "structured_content": masked_structured,
            }
        )

    @staticmethod
    async def _was_hashed_in_query(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> bool:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None:
            return False
        value: object = await fastmcp_context.get_state(PII_HASHED_IN_QUERY_STATE_KEY)
        return value is True

    def _mask_content(
        self,
        block: mt.ContentBlock,
        *,
        hashed_in_query: bool,
        tally: _MaskTally,
    ) -> mt.ContentBlock:
        if not isinstance(block, mt.TextContent):
            return block
        try:
            value: object = json.loads(block.text)
        except json.JSONDecodeError, TypeError:
            return block
        masked: object = self._mask_value(
            value,
            hashed_in_query=hashed_in_query,
            tally=tally,
        )
        return block.model_copy(
            update={"text": json.dumps(masked, separators=(",", ":"), default=str)}
        )

    def _mask_value(
        self,
        value: object,
        *,
        hashed_in_query: bool,
        tally: _MaskTally,
    ) -> Any:
        if isinstance(value, dict):
            masked_mapping: dict[str, Any] = {}
            for key, item in value.items():
                rule: PiiColumn | None = self._rules.get(str(key).lower())
                if rule is None:
                    masked_mapping[str(key)] = self._mask_value(
                        item,
                        hashed_in_query=hashed_in_query,
                        tally=tally,
                    )
                    continue
                if rule.action == "drop":
                    tally.removed.add(str(key))
                    continue
                if rule.action == "allow" or rule.action == "block":
                    masked_mapping[str(key)] = item
                    continue
                if hashed_in_query:
                    masked_mapping[str(key)] = item
                    continue
                tally.masked.add(str(key))
                masked_mapping[str(key)] = self._transform(item, rule)
            return masked_mapping
        if isinstance(value, list):
            return [
                self._mask_value(
                    item,
                    hashed_in_query=hashed_in_query,
                    tally=tally,
                )
                for item in value
            ]
        return value

    @staticmethod
    def _transform(value: object, rule: PiiColumn) -> object:
        if value is None:
            return value
        text: str = str(value)
        if rule.action != "mask":
            return value
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
        report: ToolCallReport | None = await get_report(context)
        with span("guard.review_call", server=self._server_name, tool=tool_name):
            call_verdict: GuardVerdict = await self._guard.review_call(
                self._server_name,
                tool_name,
                arguments,
                self._policy_context,
            )
        if report is not None:
            report.call_decision = call_verdict.decision
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
        protections: str | None = await self._describe_protections(context, report)
        with span("guard.review_result", server=self._server_name, tool=tool_name):
            result_verdict: GuardVerdict = await self._guard.review_result(
                self._server_name,
                tool_name,
                result_text,
                self._policy_context,
                protections,
            )
        if report is not None:
            report.result_decision = result_verdict.decision
        if result_verdict.decision == "block":
            raise ToolGuardedError(
                self._server_name,
                tool_name,
                result_verdict.reason,
            )
        return result

    @staticmethod
    async def _describe_protections(
        context: MiddlewareContext[mt.CallToolRequestParams],
        report: ToolCallReport | None,
    ) -> str | None:
        """Tell the guard how the query was already de-identified."""
        hashed: list[str] = await LlmGuardMiddleware._hashed_columns(context)
        dropped: list[str] = list(report.dropped_columns) if report else []
        sentences: list[str] = []
        if hashed:
            sentences.append(
                "The gateway replaced these columns with per-session keyed SHA-256 "
                f"digests inside the SQL query: {', '.join(hashed)}. Their values in "
                "the result are irreversible hex digests, not raw personal data, and "
                "satisfy the policy masking requirement."
            )
        if dropped:
            sentences.append(
                "The gateway also removed these columns from the query before it ran, "
                f"so the result cannot contain them: {', '.join(dropped)}."
            )
        if not sentences:
            return None
        return " ".join(sentences)

    @staticmethod
    async def _hashed_columns(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> list[str]:
        fastmcp_context = context.fastmcp_context
        if fastmcp_context is None:
            return []
        columns: object = await fastmcp_context.get_state(PII_HASHED_COLUMNS_STATE_KEY)
        if not isinstance(columns, list):
            return []
        return [str(column) for column in columns]
