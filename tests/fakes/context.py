"""Minimal FastMCP context stand-in for middleware unit tests."""

from typing import Any


class FakeFastMcpContext:
    """Expose session_id and request-scoped state without a real MCP server."""

    def __init__(self, session_id: str) -> None:
        self.session_id: str = session_id
        self._state: dict[str, Any] = {}

    async def set_state(
        self,
        key: str,
        value: Any,
        *,
        serializable: bool = True,
    ) -> None:
        del serializable
        self._state[key] = value

    async def get_state(self, key: str) -> Any:
        return self._state.get(key)
