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
from fastmcp.server.middleware import Middleware

from app.core.config import GuardSettings
from app.core.logging import logger
from app.exceptions import ProxyBuildError
from app.middleware import (
    LlmGuardMiddleware,
    PiiHashRewriteMiddleware,
    PiiMaskingMiddleware,
    SessionAuthMiddleware,
    SqlPolicyMiddleware,
    ToolPolicyMiddleware,
    ToolReportMiddleware,
)
from app.models import HttpSource, McpServerConfig, McpSource, StdioSource
from app.policies import Policy, SqlPolicy
from app.services.guard import GuardService
from app.services.history import HistoryStore
from app.services.rewriter import PiiQueryRewriter
from app.services.session import SessionStore


class ProxyFactory:
    """Turns a validated server definition into a mountable FastMCP server.

    The returned server speaks MCP to its clients and forwards every request to
    the source server, with the tool policy applied in between.
    """

    def __init__(
        self,
        environ: Mapping[str, str] | None = None,
        guard_service: GuardService | None = None,
        guard_settings: GuardSettings | None = None,
        session_store: SessionStore | None = None,
        pii_query_rewriter: PiiQueryRewriter | None = None,
        history_store: HistoryStore | None = None,
    ) -> None:
        self._environ: Mapping[str, str] = (
            environ if environ is not None else os.environ
        )
        self._guard_service: GuardService | None = guard_service
        self._guard_settings: GuardSettings = guard_settings or GuardSettings()
        self._session_store: SessionStore | None = session_store
        self._pii_query_rewriter: PiiQueryRewriter | None = pii_query_rewriter
        self._history_store: HistoryStore | None = history_store

    def create(
        self,
        config: McpServerConfig,
        policy: Policy | None = None,
    ) -> FastMCP:
        transport: ClientTransport = self._build_transport(config)
        logger.info(
            "Proxying server %r via %s",
            config.name,
            type(transport).__name__,
        )
        middleware: list[Middleware] = []
        if self._session_store is not None:
            middleware.append(
                SessionAuthMiddleware(self._session_store, server_name=config.name)
            )
        # Outermost of the tool chain: it must see the final result, after the
        # guard and the masking fallback have run.
        middleware.append(
            ToolReportMiddleware(
                server_name=config.name,
                history_store=self._history_store,
                session_store=self._session_store,
            )
        )
        middleware.append(ToolPolicyMiddleware(config.tools, server_name=config.name))
        sql_policy: SqlPolicy | None = policy if isinstance(policy, SqlPolicy) else None
        if sql_policy is not None:
            middleware.append(SqlPolicyMiddleware(sql_policy, server_name=config.name))
        guard_enabled: bool = (
            config.guard.enabled
            if config.guard.enabled is not None
            else self._guard_settings.enabled
        )
        if guard_enabled:
            if self._guard_service is None:
                raise ProxyBuildError(
                    config.name,
                    "safety guard enabled without a configured guard service",
                )
            inspect_results: bool = (
                config.guard.inspect_results
                if config.guard.inspect_results is not None
                else self._guard_settings.inspect_results
            )
            middleware.append(
                LlmGuardMiddleware(
                    self._guard_service,
                    server_name=config.name,
                    inspect_results=inspect_results,
                    policy=sql_policy,
                )
            )
        if (
            sql_policy is not None
            and self._pii_query_rewriter is not None
            and self._session_store is not None
        ):
            middleware.append(
                PiiHashRewriteMiddleware(
                    self._pii_query_rewriter,
                    sql_policy,
                    self._session_store,
                    server_name=config.name,
                    on_error=self._guard_settings.on_error,
                )
            )
        if sql_policy is not None:
            middleware.append(PiiMaskingMiddleware(sql_policy))
        return create_proxy(
            transport,
            name=config.name,
            instructions=config.description,
            middleware=middleware,
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
