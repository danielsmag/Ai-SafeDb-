"""Unit tests for LLM in-query PII hashing."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

import pytest
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types as mt

from app.connectors.models import ClientInfo
from app.exceptions import LlmUnavailableError, PolicyViolationError
from app.llm import ChatCompletion, ChatMessage
from app.llm.protocols import JsonSchema, ReasoningEffort, ToolDefinition
from app.middleware import (
    PII_HASHED_COLUMNS_STATE_KEY,
    PII_HASHED_IN_QUERY_STATE_KEY,
    LlmGuardMiddleware,
    PiiHashRewriteMiddleware,
    PiiMaskingMiddleware,
)
from app.policies import SqlPolicy
from app.policies.sql import SqlPolicyEnforcer
from app.services.guard import GuardService
from app.services.rewriter import DATA_KEY_PLACEHOLDER, PiiQueryRewriter, QueryRewrite
from app.services.session import MemorySessionService
from tests.fakes import FakeFastMcpContext
from tests.fakes import FakeLlmClient as GuardLlmClient
from tests.test_policies import build_policy


def _guard_completion(decision: str, reason: str) -> ChatCompletion:
    return ChatCompletion(
        message=ChatMessage(
            role="assistant",
            content=json.dumps(
                {"decision": decision, "reason": reason, "confidence": 0.9}
            ),
        )
    )


class FakeLlmClient:
    """Returns a canned chat completion for rewriter tests."""

    def __init__(self, content: str | None, *, fail: bool = False) -> None:
        self._content: str | None = content
        self._fail: bool = fail
        self.last_messages: list[ChatMessage] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        schema: JsonSchema | None = None,
        tools: list[ToolDefinition] | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> ChatCompletion:
        del model, schema, tools, reasoning_effort
        self.last_messages = list(messages)
        if self._fail:
            raise LlmUnavailableError("fake llm down")
        return ChatCompletion(
            message=ChatMessage(role="assistant", content=self._content)
        )

    async def close(self) -> None:
        return None


class SequenceLlmClient:
    """Returns queued contents in order, one per completion call."""

    def __init__(self, contents: list[str]) -> None:
        self._contents: list[str] = list(contents)
        self.calls: int = 0
        self.last_messages: list[ChatMessage] = []

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        model: str,
        schema: JsonSchema | None = None,
        tools: list[ToolDefinition] | None = None,
        reasoning_effort: ReasoningEffort | None = None,
    ) -> ChatCompletion:
        del model, schema, tools, reasoning_effort
        self.last_messages = list(messages)
        self.calls += 1
        content: str = self._contents.pop(0)
        return ChatCompletion(message=ChatMessage(role="assistant", content=content))

    async def close(self) -> None:
        return None


def _rewritten_email_sql() -> str:
    return (
        "SELECT encode(sha256(convert_to("
        f"'{DATA_KEY_PLACEHOLDER}' || email::text, 'UTF8')), 'hex') AS email "
        "FROM public.customers"
    )


async def test_rewriter_returns_placeholder_sql() -> None:
    rewrite: QueryRewrite = QueryRewrite(rewritten_sql=_rewritten_email_sql())
    client: FakeLlmClient = FakeLlmClient(rewrite.model_dump_json())
    rewriter: PiiQueryRewriter = PiiQueryRewriter(
        client,
        model="test-model",
        on_error="block",
    )

    result: str | None = await rewriter.rewrite(
        "SELECT email FROM public.customers",
        "postgres",
        {"public.customers": ["email"]},
    )

    assert result is not None
    assert DATA_KEY_PLACEHOLDER in result
    assert "email" in result
    user_content: str | None = client.last_messages[1].content
    assert user_content is not None
    assert DATA_KEY_PLACEHOLDER in user_content
    assert "email" in user_content


async def test_rewriter_skips_when_no_pii_columns() -> None:
    client: FakeLlmClient = FakeLlmClient("{}")
    rewriter: PiiQueryRewriter = PiiQueryRewriter(
        client,
        model="test-model",
        on_error="block",
    )

    result: str | None = await rewriter.rewrite(
        "SELECT id FROM public.customers",
        "postgres",
        {},
    )

    assert result is None
    assert client.last_messages == []


async def test_rewriter_rejects_unparseable_output_fail_closed() -> None:
    client: FakeLlmClient = FakeLlmClient(
        QueryRewrite(rewritten_sql="NOT VALID SQL (((((").model_dump_json()
    )
    rewriter: PiiQueryRewriter = PiiQueryRewriter(
        client,
        model="test-model",
        on_error="block",
    )

    with pytest.raises(LlmUnavailableError):
        await rewriter.rewrite(
            "SELECT email FROM public.customers",
            "postgres",
            {"public.customers": ["email"]},
        )


async def test_rewriter_fail_open_returns_none() -> None:
    client: FakeLlmClient = FakeLlmClient(None, fail=True)
    rewriter: PiiQueryRewriter = PiiQueryRewriter(
        client,
        model="test-model",
        on_error="allow",
    )

    result: str | None = await rewriter.rewrite(
        "SELECT email FROM public.customers",
        "postgres",
        {"public.customers": ["email"]},
    )

    assert result is None


async def test_hashable_pii_columns_excludes_block() -> None:
    enforcer: SqlPolicyEnforcer = SqlPolicyEnforcer(build_policy())
    columns: dict[str, list[str]] = enforcer.hashable_pii_columns(
        "SELECT email, ip_address FROM public.customers"
    )
    assert columns == {"public.customers": ["email", "ip_address"]}


async def test_hashable_pii_columns_only_projected_columns() -> None:
    enforcer: SqlPolicyEnforcer = SqlPolicyEnforcer(build_policy())
    columns: dict[str, list[str]] = enforcer.hashable_pii_columns(
        "SELECT id, ip_address FROM public.customers ORDER BY id LIMIT 3"
    )
    assert columns == {"public.customers": ["ip_address"]}


async def test_hashable_pii_columns_skips_query_without_pii_projection() -> None:
    enforcer: SqlPolicyEnforcer = SqlPolicyEnforcer(build_policy())
    assert enforcer.hashable_pii_columns("SELECT COUNT(*) FROM public.customers") == {}


async def test_rewriter_rejects_hashed_string_literals() -> None:
    literal_rewrite: QueryRewrite = QueryRewrite(
        rewritten_sql=(
            "SELECT encode(sha256(convert_to("
            f"'{DATA_KEY_PLACEHOLDER}' || 'email', 'UTF8')), 'hex') AS email "
            "FROM public.customers"
        )
    )
    rewriter: PiiQueryRewriter = PiiQueryRewriter(
        FakeLlmClient(literal_rewrite.model_dump_json()),
        model="test-model",
        on_error="allow",
    )

    result: str | None = await rewriter.rewrite(
        "SELECT email FROM public.customers",
        "postgres",
        {"public.customers": ["email"]},
    )

    assert result is None


async def test_rewriter_rejects_changed_output_columns() -> None:
    extra_columns: QueryRewrite = QueryRewrite(
        rewritten_sql=(
            "SELECT encode(sha256(convert_to("
            f"'{DATA_KEY_PLACEHOLDER}' || email::text, 'UTF8')), 'hex') AS email, "
            "encode(sha256(convert_to("
            f"'{DATA_KEY_PLACEHOLDER}' || phone::text, 'UTF8')), 'hex') AS phone "
            "FROM public.customers"
        )
    )
    rewriter: PiiQueryRewriter = PiiQueryRewriter(
        FakeLlmClient(extra_columns.model_dump_json()),
        model="test-model",
        on_error="allow",
    )

    result: str | None = await rewriter.rewrite(
        "SELECT email FROM public.customers",
        "postgres",
        {"public.customers": ["email"]},
    )

    assert result is None


async def test_rewriter_retries_after_rejection() -> None:
    bad: QueryRewrite = QueryRewrite(rewritten_sql="NOT VALID SQL (((((")
    good: QueryRewrite = QueryRewrite(rewritten_sql=_rewritten_email_sql())
    client: SequenceLlmClient = SequenceLlmClient(
        [bad.model_dump_json(), good.model_dump_json()]
    )
    rewriter: PiiQueryRewriter = PiiQueryRewriter(
        client,
        model="test-model",
        on_error="block",
    )

    result: str | None = await rewriter.rewrite(
        "SELECT email FROM public.customers",
        "postgres",
        {"public.customers": ["email"]},
    )

    assert result is not None
    assert client.calls == 2
    retry_roles: list[str] = [message.role for message in client.last_messages]
    assert retry_roles == ["system", "user", "assistant", "user"]


async def _open_session_store() -> tuple[MemorySessionService, str, str]:
    store: MemorySessionService = MemorySessionService()
    api_key = await store.authenticate("aisk_dev_local_00000000000000000001")
    assert api_key is not None
    mcp_session_id: str = f"mcp-{uuid4()}"
    session = await store.open_session(
        mcp_session_id=mcp_session_id,
        api_key=api_key,
        server_name="postgres",
        client_info=ClientInfo(name="test", version="1"),
    )
    return store, mcp_session_id, session.data_key


async def test_middleware_rewrites_sql_and_substitutes_data_key() -> None:
    store: MemorySessionService
    mcp_session_id: str
    data_key: str
    store, mcp_session_id, data_key = await _open_session_store()
    rewrite: QueryRewrite = QueryRewrite(rewritten_sql=_rewritten_email_sql())
    rewriter: PiiQueryRewriter = PiiQueryRewriter(
        FakeLlmClient(rewrite.model_dump_json()),
        model="test-model",
        on_error="block",
    )
    middleware: PiiHashRewriteMiddleware = PiiHashRewriteMiddleware(
        rewriter,
        build_policy(),
        store,
        server_name="postgres",
        on_error="block",
    )
    fake_ctx: FakeFastMcpContext = FakeFastMcpContext(mcp_session_id)
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="query",
            arguments={"sql": "SELECT email FROM public.customers"},
        ),
        fastmcp_context=fake_ctx,  # type: ignore[arg-type]
    )
    captured_sql: list[str] = []

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        args: dict[str, Any] | None = context.message.arguments
        assert args is not None
        captured_sql.append(str(args["sql"]))
        return ToolResult(content=[mt.TextContent(type="text", text="ok")])

    await middleware.on_call_tool(context, call_next)

    assert len(captured_sql) == 1
    assert DATA_KEY_PLACEHOLDER not in captured_sql[0]
    assert data_key in captured_sql[0]
    assert await fake_ctx.get_state(PII_HASHED_IN_QUERY_STATE_KEY) is True
    assert await fake_ctx.get_state(PII_HASHED_COLUMNS_STATE_KEY) == ["email"]


async def test_middleware_rejects_malicious_rewrite_fail_closed() -> None:
    store: MemorySessionService
    mcp_session_id: str
    store, mcp_session_id, _ = await _open_session_store()
    malicious: QueryRewrite = QueryRewrite(
        rewritten_sql=f"{_rewritten_email_sql()} WHERE pg_sleep(1) IS NOT NULL"
    )
    middleware: PiiHashRewriteMiddleware = PiiHashRewriteMiddleware(
        PiiQueryRewriter(
            FakeLlmClient(malicious.model_dump_json()),
            model="test-model",
            on_error="block",
        ),
        build_policy(),
        store,
        server_name="postgres",
        on_error="block",
    )
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="query",
            arguments={"sql": "SELECT email FROM public.customers"},
        ),
        fastmcp_context=FakeFastMcpContext(mcp_session_id),  # type: ignore[arg-type]
    )

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(content=[mt.TextContent(type="text", text="ok")])

    with pytest.raises(PolicyViolationError, match="rewritten SQL rejected"):
        await middleware.on_call_tool(context, call_next)


async def test_middleware_fail_open_forwards_original() -> None:
    store: MemorySessionService
    mcp_session_id: str
    store, mcp_session_id, _ = await _open_session_store()
    middleware: PiiHashRewriteMiddleware = PiiHashRewriteMiddleware(
        PiiQueryRewriter(
            FakeLlmClient(None, fail=True),
            model="test-model",
            on_error="allow",
        ),
        build_policy(),
        store,
        server_name="postgres",
        on_error="allow",
    )
    original_sql: str = "SELECT email FROM public.customers"
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="query",
            arguments={"sql": original_sql},
        ),
        fastmcp_context=FakeFastMcpContext(mcp_session_id),  # type: ignore[arg-type]
    )
    captured_sql: list[str] = []

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        args: dict[str, Any] | None = context.message.arguments
        assert args is not None
        captured_sql.append(str(args["sql"]))
        return ToolResult(content=[mt.TextContent(type="text", text="ok")])

    await middleware.on_call_tool(context, call_next)
    assert captured_sql == [original_sql]


async def test_masking_skipped_when_hashed_in_query_flag_set() -> None:
    policy: SqlPolicy = build_policy()
    masking: PiiMaskingMiddleware = PiiMaskingMiddleware(policy)
    fake_ctx: FakeFastMcpContext = FakeFastMcpContext("mcp-sess")
    await fake_ctx.set_state(PII_HASHED_IN_QUERY_STATE_KEY, True)
    payload: list[dict[str, str]] = [
        {"email": "hashed-value", "city": "Testville"},
    ]
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(name="query", arguments={}),
        fastmcp_context=fake_ctx,  # type: ignore[arg-type]
    )

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(
            content=[mt.TextContent(type="text", text='[{"email":"hashed-value"}]')],
            structured_content={"rows": payload},
        )

    result: ToolResult = await masking.on_call_tool(context, call_next)
    assert result.structured_content == {"rows": payload}


async def test_result_guard_skips_llm_when_columns_were_hashed() -> None:
    """Hashed-column protections short-circuit the result LLM guard."""
    client: GuardLlmClient = GuardLlmClient(
        [_guard_completion("allow", "narrow read")]
    )
    guard: GuardService = GuardService(
        client,
        "guard-model",
        "block",
        cache_ttl_seconds=0,
    )
    middleware: LlmGuardMiddleware = LlmGuardMiddleware(
        guard,
        server_name="postgres",
        inspect_results=True,
        policy=build_policy(),
    )
    fake_ctx: FakeFastMcpContext = FakeFastMcpContext("mcp-sess")
    await fake_ctx.set_state(PII_HASHED_COLUMNS_STATE_KEY, ["ip_address"])
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="query",
            arguments={"sql": "SELECT id, ip_address FROM public.customers LIMIT 3"},
        ),
        fastmcp_context=fake_ctx,  # type: ignore[arg-type]
    )

    async def call_next(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(
            content=[mt.TextContent(type="text", text='[{"id":1,"ip_address":"0d88"}]')]
        )

    result: ToolResult = await middleware.on_call_tool(context, call_next)

    assert not result.is_error
    # Call guard only; result path trusts protections without another LLM call.
    assert len(client.calls) == 1


async def test_data_key_with_quote_is_escaped() -> None:
    escaped: str = PiiHashRewriteMiddleware._substitute_data_key(
        f"SELECT '{DATA_KEY_PLACEHOLDER}'",
        "abc'def",
    )
    assert escaped == "SELECT 'abc''def'"
