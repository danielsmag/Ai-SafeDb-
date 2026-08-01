"""ASGI middleware that closes gateway sessions on MCP HTTP DELETE."""

from __future__ import annotations

from starlette.types import ASGIApp, Receive, Scope, Send

from app.core.logging import logger
from app.services.session import SessionStore

_SESSION_HEADER: str = b"mcp-session-id"


class SessionTerminateMiddleware:
    """Mark gateway sessions closed when the client terminates the MCP session.

    Streamable HTTP clients send ``DELETE`` with ``mcp-session-id`` to end a
    session. We close our Postgres row, then forward the request to FastMCP.
    """

    def __init__(self, app: ASGIApp, store: SessionStore) -> None:
        self._app: ASGIApp = app
        self._store: SessionStore = store
        self.lifespan: object | None = getattr(app, "lifespan", None)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and scope.get("method") == "DELETE":
            mcp_session_id: str | None = self._header_value(scope, _SESSION_HEADER)
            if mcp_session_id:
                closed: bool = await self._store.close_session(mcp_session_id)
                if closed:
                    logger.info(
                        "Client DELETE closed MCP session mcp_session_id=%r",
                        mcp_session_id,
                    )
        await self._app(scope, receive, send)

    @staticmethod
    def _header_value(scope: Scope, name: bytes) -> str | None:
        headers: list[tuple[bytes, bytes]] = list(scope.get("headers") or [])
        for key, value in headers:
            if key.lower() == name:
                return value.decode("latin-1")
        return None


def wrap_with_session_terminate(app: ASGIApp, store: SessionStore) -> ASGIApp:
    """Wrap an MCP ASGI app while preserving ``lifespan`` if present."""
    return SessionTerminateMiddleware(app, store)
