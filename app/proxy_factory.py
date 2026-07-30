"""Construction of a FastMCP proxy for each source MCP server."""

import os
from collections.abc import Mapping
from datetime import timedelta

from fastmcp import FastMCP
from fastmcp.client.transports import (
    ClientTransport,
    SSETransport,
    StdioTransport,
    StreamableHttpTransport,
)
from fastmcp.server import create_proxy

from app.core.logging import logger
from app.exceptions import ProxyBuildError
from app.middleware import ToolPolicyMiddleware
from app.models import HttpSource, McpServerConfig, McpSource, StdioSource


class ProxyFactory:
    """Turns a validated server definition into a mountable FastMCP server.

    The returned server speaks MCP to its clients and forwards every request to
    the source server, with the tool policy applied in between.
    """

    def __init__(self, environ: Mapping[str, str] | None = None) -> None:
        self._environ: Mapping[str, str] = (
            environ if environ is not None else os.environ
        )

    def create(self, config: McpServerConfig) -> FastMCP:
        transport: ClientTransport = self._build_transport(config)
        logger.info(
            "Proxying server %r via %s",
            config.name,
            type(transport).__name__,
        )
        return create_proxy(
            transport,
            name=config.name,
            instructions=config.description,
            middleware=[ToolPolicyMiddleware(config.tools, server_name=config.name)],
        )

    def _build_transport(self, config: McpServerConfig) -> ClientTransport:
        source: McpSource = config.source
        if isinstance(source, HttpSource):
            return self._build_http_transport(source)
        if isinstance(source, StdioSource):
            return self._build_stdio_transport(source)
        raise ProxyBuildError(
            config.name, f"unsupported source type {type(source).__name__}"
        )

    def _build_http_transport(self, source: HttpSource) -> ClientTransport:
        timeout: timedelta | None = (
            timedelta(seconds=source.read_timeout_seconds)
            if source.read_timeout_seconds is not None
            else None
        )
        transport_cls: type[SSETransport] | type[StreamableHttpTransport] = (
            SSETransport if source.transport == "sse" else StreamableHttpTransport
        )
        return transport_cls(
            url=str(source.url),
            headers=source.headers or None,
            sse_read_timeout=timeout,
        )

    def _build_stdio_transport(self, source: StdioSource) -> ClientTransport:
        # The child process inherits the gateway environment so that PATH and
        # friends keep working; explicit entries win.
        env: dict[str, str] | None = (
            {**self._environ, **source.env} if source.env else None
        )
        return StdioTransport(
            command=source.command,
            args=source.args,
            env=env,
            cwd=source.cwd,
            keep_alive=True,
        )
