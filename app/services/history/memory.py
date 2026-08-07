"""In-memory tool-call history store for tests and local fakes."""

from collections.abc import Sequence
from datetime import datetime
from operator import attrgetter
from uuid import UUID

from app.services.history.models import (
    ApiKeyFacet,
    HistoryFacets,
    ToolCallHistory,
    ToolCallHistoryPage,
)


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

    async def list_all_calls(
        self,
        *,
        limit: int,
        offset: int,
        server: str | None = None,
        session_id: UUID | None = None,
        user_id: UUID | None = None,
        tool_names: Sequence[str] | None = None,
        statuses: Sequence[str] | None = None,
        api_key_ids: Sequence[UUID] | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        sort_by: str | None = None,
        sort_order: str | None = None,
    ) -> ToolCallHistoryPage:
        tool_set: set[str] | None = set(tool_names) if tool_names else None
        status_set: set[str] | None = set(statuses) if statuses else None
        key_set: set[UUID] | None = set(api_key_ids) if api_key_ids else None
        matching: list[ToolCallHistory] = [
            entry
            for entry in self._entries
            if (server is None or entry.server_name == server)
            and (session_id is None or entry.session_id == session_id)
            and (user_id is None or entry.user_id == user_id)
            and (tool_set is None or entry.tool_name in tool_set)
            and (status_set is None or entry.status in status_set)
            and (key_set is None or entry.api_key_id in key_set)
            and (since is None or entry.created_at >= since)
            and (until is None or entry.created_at <= until)
        ]
        allowed_sort: set[str] = {
            "created_at",
            "server_name",
            "tool_name",
            "status",
            "duration_ms",
            "api_key_name",
            "username",
        }
        sort_column: str = sort_by if sort_by in allowed_sort else "created_at"
        reverse: bool = sort_order != "asc"
        matching.sort(key=attrgetter(sort_column), reverse=reverse)
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

    async def get_call_admin(self, call_id: UUID) -> ToolCallHistory | None:
        return next(
            (entry for entry in self._entries if entry.id == call_id),
            None,
        )

    async def list_facets(self) -> HistoryFacets:
        servers: list[str] = sorted({entry.server_name for entry in self._entries})
        tools: list[str] = sorted({entry.tool_name for entry in self._entries})
        keys: dict[UUID, str] = {
            entry.api_key_id: entry.api_key_name for entry in self._entries
        }
        api_keys: list[ApiKeyFacet] = sorted(
            (ApiKeyFacet(id=key_id, name=name) for key_id, name in keys.items()),
            key=lambda facet: facet.name,
        )
        return HistoryFacets(servers=servers, tools=tools, api_keys=api_keys)
