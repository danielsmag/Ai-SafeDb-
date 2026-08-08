"""Tests for tool-call persistence and authenticated history APIs."""

from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI
from fastmcp.server.middleware import MiddlewareContext
from fastmcp.tools import ToolResult
from mcp import types as mt

from app.connectors.models import ApiKey, ClientInfo, SessionRecord
from app.domain.gateway_application import GatewayApplication
from app.exceptions import ToolBlockedError
from app.middleware import ToolReportMiddleware
from app.proxy_factory import ProxyFactory
from app.services.auth import DEV_PASSWORD, DEV_USERNAME, MemoryAuthService
from app.services.config_loader import ConfigLoader
from app.services.history import MemoryHistoryStore, ToolCallHistory
from app.services.session import DEV_API_KEY, MemorySessionService
from app.settings import AppSettings
from tests.fakes import FakeFastMcpContext

OTHER_API_KEY: str = "aisk_other_local_00000000000000000002"


def history_entry(
    session: SessionRecord,
    *,
    tool_name: str = "query",
) -> ToolCallHistory:
    return ToolCallHistory(
        session_id=session.id,
        mcp_session_id=session.mcp_session_id,
        api_key_id=session.api_key_id,
        api_key_name=session.api_key_name,
        server_name=session.server_name,
        tool_name=tool_name,
        original_arguments={"sql": "SELECT id FROM customers"},
        original_sql=["SELECT id FROM customers"],
        executed_sql=["SELECT id FROM customers"],
        duration_ms=2.5,
    )


async def open_test_session(
    store: MemorySessionService,
    api_key: str,
    mcp_session_id: str,
) -> SessionRecord:
    principal: ApiKey | None = await store.authenticate(api_key)
    assert principal is not None
    return await store.open_session(
        mcp_session_id=mcp_session_id,
        api_key=principal,
        server_name="postgres",
        client_info=ClientInfo(name="pytest", version="1"),
    )


async def test_memory_history_filters_and_scopes_by_api_key() -> None:
    history: MemoryHistoryStore = MemoryHistoryStore()
    first_key: UUID = uuid4()
    second_key: UUID = uuid4()
    now: datetime = datetime.now(UTC)
    first: ToolCallHistory = ToolCallHistory(
        session_id=uuid4(),
        mcp_session_id="mcp-1",
        api_key_id=first_key,
        api_key_name="first",
        server_name="postgres",
        tool_name="query",
        created_at=now,
    )
    second: ToolCallHistory = first.model_copy(
        update={
            "id": uuid4(),
            "api_key_id": second_key,
            "api_key_name": "second",
            "mcp_session_id": "mcp-2",
        }
    )
    await history.record(first)
    await history.record(second)

    page = await history.list_calls([first_key], limit=25, offset=0)

    assert page.total == 1
    assert page.items == [first]
    assert await history.get_call([first_key], first.id) == first
    assert await history.get_call([second_key], first.id) is None


async def test_report_middleware_persists_success_and_blocked_calls() -> None:
    sessions: MemorySessionService = MemorySessionService()
    session: SessionRecord = await open_test_session(
        sessions, DEV_API_KEY, "mcp-history"
    )
    history: MemoryHistoryStore = MemoryHistoryStore()
    middleware: ToolReportMiddleware = ToolReportMiddleware(
        server_name="postgres",
        history_store=history,
        session_store=sessions,
    )
    context: MiddlewareContext[mt.CallToolRequestParams] = MiddlewareContext(
        message=mt.CallToolRequestParams(
            name="query",
            arguments={"sql": "SELECT email FROM customers"},
        ),
        fastmcp_context=FakeFastMcpContext(session.mcp_session_id),  # type: ignore[arg-type]
    )

    async def success(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        return ToolResult(content=[mt.TextContent(type="text", text="[]")])

    await middleware.on_call_tool(context, success)
    success_page = await history.list_calls(
        [session.api_key_id], limit=25, offset=0
    )
    assert success_page.items[0].status == "ok"
    assert success_page.items[0].original_sql == [
        "SELECT email FROM customers"
    ]

    async def blocked(
        context: MiddlewareContext[mt.CallToolRequestParams],
    ) -> ToolResult:
        del context
        raise ToolBlockedError("postgres", "query")

    with pytest.raises(ToolBlockedError):
        await middleware.on_call_tool(context, blocked)

    blocked_page = await history.list_calls(
        [session.api_key_id], limit=25, offset=0
    )
    assert blocked_page.total == 2
    assert blocked_page.items[0].status == "blocked"


async def test_history_api_authentication_and_owner_scoping(tmp_path: Path) -> None:
    sessions: MemorySessionService = MemorySessionService(
        raw_keys={DEV_API_KEY: "local-dev", OTHER_API_KEY: "other"}
    )
    own_session: SessionRecord = await open_test_session(
        sessions, DEV_API_KEY, "mcp-owner"
    )
    other_session: SessionRecord = await open_test_session(
        sessions, OTHER_API_KEY, "mcp-other"
    )
    history: MemoryHistoryStore = MemoryHistoryStore()
    auth: MemoryAuthService = MemoryAuthService()
    own_entry: ToolCallHistory = history_entry(own_session)
    other_entry: ToolCallHistory = history_entry(other_session, tool_name="other_query")
    await history.record(own_entry)
    await history.record(other_entry)
    settings: AppSettings = AppSettings(
        config_dir=tmp_path,
        public_base_url="http://gateway.test",
    )
    app: FastAPI = GatewayApplication(
        settings=settings,
        loader=ConfigLoader(tmp_path),
        proxy_factory=ProxyFactory(
            session_store=sessions,
            history_store=history,
        ),
        session_store=sessions,
        auth_store=auth,
        history_store=history,
    ).build()

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        unauthorized: httpx.Response = await client.get("/api/v1/client/history")
        login: httpx.Response = await client.post(
            "/api/v1/client/login",
            json={"username": DEV_USERNAME, "password": DEV_PASSWORD},
        )
        identity: httpx.Response = await client.get("/api/v1/client/me")
        page: httpx.Response = await client.get("/api/v1/client/history")
        detail: httpx.Response = await client.get(f"/api/v1/client/history/{own_entry.id}")
        hidden: httpx.Response = await client.get(f"/api/v1/client/history/{other_entry.id}")
        session_page: httpx.Response = await client.get("/api/v1/client/sessions")

    payload: dict[str, Any] = page.json()
    assert login.status_code == 200
    assert identity.json()["username"] == DEV_USERNAME
    assert page.status_code == 200
    assert payload["total"] == 1
    assert payload["items"][0]["id"] == str(own_entry.id)
    assert detail.status_code == 200
    assert hidden.status_code == 404
    assert session_page.status_code == 200
    assert len(session_page.json()["sessions"]) == 1
    assert "data_key" not in session_page.json()["sessions"][0]
    assert unauthorized.status_code == 401
