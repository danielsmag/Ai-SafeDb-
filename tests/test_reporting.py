"""Tests for the per-call report attached to guarded tool results."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types as mt

from app.connectors.models import ClientInfo
from app.llm import ChatCompletion, ChatMessage
from app.middleware import (
    LlmGuardMiddleware,
    PiiHashRewriteMiddleware,
    PiiMaskingMiddleware,
    ToolReportMiddleware,
)
from app.reporting import REPORT_META_KEY
from app.services.guard import GuardService
from app.services.rewriter import DATA_KEY_PLACEHOLDER, PiiQueryRewriter, QueryRewrite
from app.services.session import MemorySessionService
from tests.fakes import FakeFastMcpContext, FakeLlmClient
from tests.test_policies import build_policy


def _rewrite_completion() -> ChatCompletion:
    rewritten: str = (
        "SELECT id, encode(sha256(convert_to("
        f"'{DATA_KEY_PLACEHOLDER}' || email::text, 'UTF8')), 'hex') AS email "
        "FROM public.customers LIMIT 3"
    )
    return ChatCompletion(
        message=ChatMessage(
            role="assistant",
            content=QueryRewrite(rewritten_sql=rewritten).model_dump_json(),
        )
    )


def _guard_completion(decision: str) -> ChatCompletion:
    return ChatCompletion(
        message=ChatMessage(
            role="assistant",
            content=json.dumps(
                {"decision": decision, "reason": "scripted", "confidence": 0.9}
            ),
        )
    )


async def _open_session_store() -> tuple[MemorySessionService, str]:
    store: MemorySessionService = MemorySessionService()
    api_key = await store.authenticate("aisk_dev_local_00000000000000000001")
    assert api_key is not None
    mcp_session_id: str = f"mcp-{uuid4()}"
    await store.open_session(
        mcp_session_id=mcp_session_id,
        api_key=api_key,
        server_name="postgres",
        client_info=ClientInfo(name="test", version="1"),
    )
    return store, mcp_session_id


def _report_of(result: ToolResult) -> dict[str, Any]:
    assert result.meta is not None
    report: Any = result.meta[REPORT_META_KEY]
    assert isinstance(report, dict)
    return report


async def test_report_describes_drop_and_in_query_hash() -> None:
    store: MemorySessionService
    mcp_session_id: str
    store, mcp_session_id = await _open_session_store()
    rewrite: PiiHashRewriteMiddleware = PiiHashRewriteMiddleware(
        PiiQueryRewriter(
            FakeLlmClient([_rewrite_completion()]),
            model="test-model",
            on_error="block",
        ),
        build_policy(),
        store,
        server_name="postgres",
        on_error="block",
    )
    masking: PiiMaskingMiddleware = PiiMaskingMiddleware(build_policy())
    reporting: ToolReportMiddleware = ToolReportMiddleware(server_name="postgres")
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="query",
            arguments={
                "sql": "SELECT id, email, credit_card FROM public.customers LIMIT 3"
            },
        ),
        fastmcp_context=FakeFastMcpContext(mcp_session_id),  # type: ignore[arg-type]
    )

    async def tool(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(
            content=[
                mt.TextContent(type="text", text='[{"id":1,"email":"6f1ed002ab"}]')
            ]
        )

    async def after_masking(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        return await masking.on_call_tool(context, tool)

    async def after_rewrite(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        return await rewrite.on_call_tool(context, after_masking)

    result: ToolResult = await reporting.on_call_tool(context, after_rewrite)

    report: dict[str, Any] = _report_of(result)
    assert report["server"] == "postgres"
    assert report["tool"] == "query"
    assert report["dropped_columns"] == ["credit_card"]
    assert report["hashed_columns"] == ["email"]
    assert report["masked_fields"] == []
    executed: list[str] = report["executed_sql"]
    assert len(executed) == 1
    assert DATA_KEY_PLACEHOLDER in executed[0]
    assert "credit_card" not in executed[0]


async def test_report_summary_is_appended_to_content() -> None:
    masking: PiiMaskingMiddleware = PiiMaskingMiddleware(build_policy())
    reporting: ToolReportMiddleware = ToolReportMiddleware(server_name="postgres")
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(name="query", arguments={}),
        fastmcp_context=FakeFastMcpContext("mcp-sess"),  # type: ignore[arg-type]
    )
    rows: str = json.dumps(
        [{"id": 1, "email": "person@example.com", "credit_card": "4111111111111111"}]
    )

    async def tool(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(content=[mt.TextContent(type="text", text=rows)])

    async def after_masking(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        return await masking.on_call_tool(context, tool)

    result: ToolResult = await reporting.on_call_tool(context, after_masking)

    report: dict[str, Any] = _report_of(result)
    assert report["masked_fields"] == ["email"]
    assert report["removed_fields"] == ["credit_card"]
    summary: mt.ContentBlock = result.content[-1]
    assert isinstance(summary, mt.TextContent)
    assert summary.text.startswith("aisafedb:")
    assert "masked in result email" in summary.text
    assert "removed from result credit_card" in summary.text
    payload: list[dict[str, Any]] = json.loads(
        result.content[0].text  # type: ignore[union-attr]
    )
    assert "credit_card" not in payload[0]


async def test_guard_skips_result_llm_when_columns_were_dropped() -> None:
    """Dropped-column protections short-circuit the result LLM guard."""
    client: FakeLlmClient = FakeLlmClient([_guard_completion("allow")])
    guard: LlmGuardMiddleware = LlmGuardMiddleware(
        GuardService(client, "guard-model", "block", cache_ttl_seconds=0),
        server_name="postgres",
        inspect_results=True,
        policy=build_policy(),
    )
    rewrite: PiiHashRewriteMiddleware = PiiHashRewriteMiddleware(
        PiiQueryRewriter(
            FakeLlmClient([]),
            model="test-model",
            on_error="block",
        ),
        build_policy(),
        MemorySessionService(),
        server_name="postgres",
        on_error="block",
    )
    reporting: ToolReportMiddleware = ToolReportMiddleware(server_name="postgres")
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="query",
            arguments={"sql": "SELECT id, credit_card FROM public.customers LIMIT 3"},
        ),
        fastmcp_context=FakeFastMcpContext("mcp-sess"),  # type: ignore[arg-type]
    )

    async def tool(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(content=[mt.TextContent(type="text", text='[{"id":1}]')])

    async def after_rewrite(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        return await rewrite.on_call_tool(context, tool)

    async def after_guard(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        return await guard.on_call_tool(context, after_rewrite)

    result: ToolResult = await reporting.on_call_tool(context, after_guard)

    report: dict[str, Any] = _report_of(result)
    assert report["dropped_columns"] == ["credit_card"]
    assert report["result_decision"] == "allow"
    # Call guard only; result path trusts protections without another LLM call.
    assert len(client.calls) == 1


async def test_report_notes_when_nothing_was_transformed() -> None:
    reporting: ToolReportMiddleware = ToolReportMiddleware(server_name="postgres")
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(name="list_schemas", arguments={}),
        fastmcp_context=FakeFastMcpContext("mcp-sess"),  # type: ignore[arg-type]
    )

    async def tool(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(content=[mt.TextContent(type="text", text="public")])

    result: ToolResult = await reporting.on_call_tool(context, tool)

    report: dict[str, Any] = _report_of(result)
    assert report["executed_sql"] == []
    assert report["hashed_columns"] == []
    summary: mt.ContentBlock = result.content[-1]
    assert isinstance(summary, mt.TextContent)
    assert "no PII transforms applied" in summary.text
