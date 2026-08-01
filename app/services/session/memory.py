"""In-memory session store for unit tests (no Postgres)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from app.connectors.models import ApiKey, ClientInfo, SessionRecord
from app.services.session.keys import (
    api_key_prefix,
    generate_session_data_key,
    hash_api_key,
)

# Same plaintext as init/02_gateway.sql — tests and local docs share it.
DEV_API_KEY: str = "aisk_dev_local_00000000000000000001"
_DEV_KEY_ID: UUID = UUID("00000000-0000-4000-8000-000000000001")


class MemorySessionService:
    """Process-local stand-in for :class:`SessionService`."""

    def __init__(
        self,
        raw_keys: dict[str, str] | None = None,
        idle_ttl_seconds: float = 86_400.0,
    ) -> None:
        """Map raw API key plaintext -> display name. Defaults to the dev key."""
        seeds: dict[str, str] = (
            raw_keys if raw_keys is not None else {DEV_API_KEY: "local-dev"}
        )
        self._idle_ttl_seconds: float = idle_ttl_seconds
        self._keys: dict[str, ApiKey] = {}
        self._sessions: dict[str, SessionRecord] = {}
        now: datetime = datetime.now(UTC)
        for raw_key, name in seeds.items():
            key_hash: str = hash_api_key(raw_key)
            self._keys[key_hash] = ApiKey(
                id=uuid4() if raw_key != DEV_API_KEY else _DEV_KEY_ID,
                name=name,
                key_prefix=api_key_prefix(raw_key),
                key_hash=key_hash,
                created_at=now,
            )

    async def ensure_schema(self) -> None:
        return None

    async def authenticate(self, raw_key: str) -> ApiKey | None:
        api_key: ApiKey | None = self._keys.get(hash_api_key(raw_key))
        if api_key is None or api_key.revoked_at is not None:
            return None
        return api_key

    async def open_session(
        self,
        mcp_session_id: str,
        api_key: ApiKey,
        server_name: str,
        client_info: ClientInfo,
    ) -> SessionRecord:
        now: datetime = datetime.now(UTC)
        existing: SessionRecord | None = self._sessions.get(mcp_session_id)
        session_id: UUID = existing.id if existing is not None else uuid4()
        data_key: str = (
            existing.data_key
            if existing is not None
            else generate_session_data_key()
        )
        record: SessionRecord = SessionRecord(
            id=session_id,
            mcp_session_id=mcp_session_id,
            api_key_id=api_key.id,
            api_key_name=api_key.name,
            server_name=server_name,
            data_key=data_key,
            client_name=client_info.name,
            client_version=client_info.version,
            created_at=existing.created_at if existing is not None else now,
            last_seen_at=now,
            closed_at=None,
        )
        self._sessions[mcp_session_id] = record
        return record

    async def touch(self, mcp_session_id: str) -> SessionRecord | None:
        existing: SessionRecord | None = self._sessions.get(mcp_session_id)
        if existing is None or existing.closed_at is not None:
            return None
        if self._is_idle_expired(existing.last_seen_at):
            await self.close_session(mcp_session_id)
            return None
        updated: SessionRecord = existing.model_copy(
            update={"last_seen_at": datetime.now(UTC)}
        )
        self._sessions[mcp_session_id] = updated
        return updated

    async def get_session(self, mcp_session_id: str) -> SessionRecord | None:
        existing: SessionRecord | None = self._sessions.get(mcp_session_id)
        if existing is None or existing.closed_at is not None:
            return None
        if self._is_idle_expired(existing.last_seen_at):
            await self.close_session(mcp_session_id)
            return None
        return existing

    async def get_latest_open_session(
        self, api_key_id: UUID
    ) -> SessionRecord | None:
        open_sessions: list[SessionRecord] = [
            session
            for session in self._sessions.values()
            if session.api_key_id == api_key_id and session.closed_at is None
        ]
        if not open_sessions:
            return None
        latest: SessionRecord = max(
            open_sessions, key=lambda session: session.last_seen_at
        )
        if self._is_idle_expired(latest.last_seen_at):
            await self.close_session(latest.mcp_session_id)
            return None
        return latest

    async def close_session(self, mcp_session_id: str) -> bool:
        existing: SessionRecord | None = self._sessions.get(mcp_session_id)
        if existing is None or existing.closed_at is not None:
            return False
        self._sessions[mcp_session_id] = existing.model_copy(
            update={"closed_at": datetime.now(UTC)}
        )
        return True

    def backdate_last_seen(self, mcp_session_id: str, *, seconds_ago: float) -> None:
        """Test helper: push last_seen_at into the past."""
        existing: SessionRecord | None = self._sessions.get(mcp_session_id)
        if existing is None:
            raise KeyError(mcp_session_id)
        self._sessions[mcp_session_id] = existing.model_copy(
            update={
                "last_seen_at": datetime.now(UTC) - timedelta(seconds=seconds_ago)
            }
        )

    def _is_idle_expired(self, last_seen_at: datetime) -> bool:
        if self._idle_ttl_seconds <= 0:
            return False
        idle_seconds: float = (datetime.now(UTC) - last_seen_at).total_seconds()
        return idle_seconds > self._idle_ttl_seconds
