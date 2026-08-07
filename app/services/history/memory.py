"""In-memory tool-call history store for tests and local fakes."""

from collections.abc import Sequence
from uuid import UUID

from app.services.history.models import ToolCallHistory, ToolCallHistoryPage


class MemoryHistoryStore:
    """Process-local history repository with API-key ownership filtering."""

    def __init__(self) -> None:
        self._entries: list[ToolCallHistory] = []

    async def ensure_schema(self) -> None:
        return None

    async def record(self, entry: ToolCallHistory) -> None:
        self._entries.append(entry)

    async def list_calls(
        self,
        api_key_ids: Sequence[UUID],
        *,
        limit: int,
        offset: int,
        server: str | None = None,
        session_id: UUID | None = None,
    ) -> ToolCallHistoryPage:
        key_ids: set[UUID] = set(api_key_ids)
        matching: list[ToolCallHistory] = [
            entry
            for entry in self._entries
            if entry.api_key_id in key_ids
            and (server is None or entry.server_name == server)
            and (session_id is None or entry.session_id == session_id)
        ]
        matching.sort(key=lambda entry: entry.created_at, reverse=True)
        return ToolCallHistoryPage(
            items=matching[offset : offset + limit],
            total=len(matching),
        )

    async def get_call(
        self, api_key_ids: Sequence[UUID], call_id: UUID
    ) -> ToolCallHistory | None:
        key_ids: set[UUID] = set(api_key_ids)
        return next(
            (
                entry
                for entry in self._entries
                if entry.id == call_id and entry.api_key_id in key_ids
            ),
            None,
        )
