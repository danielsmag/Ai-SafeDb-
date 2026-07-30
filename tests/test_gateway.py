import sys
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from fastmcp.exceptions import ToolError

from app.config_loader import ConfigLoader
from app.main import GatewayApplication
from app.proxy_factory import ProxyFactory
from app.settings import AppSettings

SOURCE_SERVER = Path(__file__).parent / "fixtures" / "source_server.py"
BASE_URL = "http://gateway.test"


def build_app(config_dir: Path) -> FastAPI:
    settings = AppSettings(config_dir=config_dir, public_base_url=BASE_URL)
    gateway = GatewayApplication(
        settings=settings,
        loader=ConfigLoader(config_dir, environ={"PYTHON_BIN": sys.executable}),
        proxy_factory=ProxyFactory(),
    )
    return gateway.build()


@asynccontextmanager
async def running(app: FastAPI) -> AsyncIterator[FastAPI]:
    """Run the app's lifespan, which starts the mounted MCP session managers."""
    async with app.router.lifespan_context(app):
        yield app


def asgi_client(app: FastAPI) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url=BASE_URL,
    )


def mcp_client(app: FastAPI, path: str) -> Client:
    """An MCP client that talks to the gateway in-process over ASGI."""

    def client_factory(**kwargs: Any) -> httpx.AsyncClient:
        kwargs.pop("base_url", None)
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=BASE_URL,
            **kwargs,
        )

    return Client(
        StreamableHttpTransport(
            url=f"{BASE_URL}{path}",
            httpx_client_factory=client_factory,
        )
    )


@pytest.fixture
def gateway_app(config_dir: Path, write_config) -> FastAPI:
    write_config(
        "source.yaml",
        f"""
        name: source
        description: Test source server.
        source:
          transport: stdio
          command: ${{PYTHON_BIN}}
          args: ["{SOURCE_SERVER}"]
        tools:
          block: [delete_*]
        """,
    )
    return build_app(config_dir)


async def test_health_and_server_listing(gateway_app: FastAPI) -> None:
    async with running(gateway_app) as app, asgi_client(app) as client:
        health = await client.get("/health")
        servers = await client.get("/servers")

    assert health.status_code == 200
    assert health.json()["status"] == "ok"
    assert health.json()["servers"] == 1

    listing = servers.json()["servers"]
    assert listing == [
        {
            "name": "source",
            "description": "Test source server.",
            "transport": "stdio",
            "url": f"{BASE_URL}/mcp/source",
            "tools": {"allow": [], "block": ["delete_*"]},
        }
    ]


async def test_blocked_tool_is_hidden_and_rejected(gateway_app: FastAPI) -> None:
    async with running(gateway_app) as app, mcp_client(app, "/mcp/source") as client:
        tools = await client.list_tools()
        assert [tool.name for tool in tools] == ["read_thing"]

        result = await client.call_tool("read_thing", {"name": "abc"})
        assert result.data == "read:abc"

        with pytest.raises(ToolError, match="not exposed by gateway server"):
            await client.call_tool("delete_thing", {"name": "abc"})


async def test_empty_config_dir_serves_only_gateway_routes(config_dir: Path) -> None:
    async with running(build_app(config_dir)) as app, asgi_client(app) as client:
        health = await client.get("/health")
        missing = await client.get("/mcp/source")

    assert health.json()["servers"] == 0
    assert missing.status_code == 404
