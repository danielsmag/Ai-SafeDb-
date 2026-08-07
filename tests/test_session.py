"""Unit tests for API-key hashing and in-memory session recognition."""

from uuid import UUID

import pytest

from app.connectors.models import ClientInfo, SessionRecord
from app.core.config import DatabaseSettings
from app.core.logging import (
    NO_SESSION,
    api_key_name_var,
    bind_session,
    mcp_session_id_var,
    session_id_var,
)
from app.services.auth import DEV_USER_ID
from app.services.session import (
    DEV_API_KEY,
    MemorySessionService,
    api_key_prefix,
    generate_session_data_key,
    hash_api_key,
)


def test_hash_api_key_is_stable_sha256() -> None:
    digest: str = hash_api_key(DEV_API_KEY)
    assert digest == (
        "c869076a37be0ccc37c1e36ffb64454b288ae874390783b03277f71978258183"
    )
    assert api_key_prefix(DEV_API_KEY) == "aisk_dev"


def test_generate_session_data_key_is_unique() -> None:
    first: str = generate_session_data_key()
    second: str = generate_session_data_key()
    assert first
    assert second
    assert first != second


def test_database_settings_read_safe_db_schema_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("SAFE_DB_SCHEMA", "my_gateway")
    settings: DatabaseSettings = DatabaseSettings()
    assert settings.schema_name == "my_gateway"


def test_database_settings_reject_unsafe_schema_name() -> None:
    with pytest.raises(ValueError, match="schema_name must match"):
        DatabaseSettings(schema_name="bad-schema;drop")


async def test_memory_session_authenticate_and_open() -> None:
    store: MemorySessionService = MemorySessionService()
    api_key = await store.authenticate(DEV_API_KEY)
    assert api_key is not None
    assert api_key.name == "local-dev"

    assert await store.authenticate("wrong-key") is None

    session = await store.open_session(
        mcp_session_id="mcp-sess-1",
        api_key=api_key,
        server_name="postgres",
        client_info=ClientInfo(name="test-client", version="1.0"),
    )
    assert session.mcp_session_id == "mcp-sess-1"
    assert session.api_key_name == "local-dev"
    assert session.client_name == "test-client"
    assert session.data_key

    touched = await store.touch("mcp-sess-1")
    assert touched is not None
    assert touched.id == session.id
    assert touched.data_key == session.data_key
    assert await store.touch("missing") is None
    assert await store.list_api_key_ids_for_user(DEV_USER_ID) == [api_key.id]
    listed_sessions: list[SessionRecord] = await store.list_sessions([api_key.id])
    assert [listed.id for listed in listed_sessions] == [session.id]


async def test_memory_session_data_key_stable_across_reconnect() -> None:
    store: MemorySessionService = MemorySessionService()
    api_key = await store.authenticate(DEV_API_KEY)
    assert api_key is not None

    first = await store.open_session(
        mcp_session_id="mcp-stable-key",
        api_key=api_key,
        server_name="postgres",
        client_info=ClientInfo(name="c", version="1"),
    )
    second = await store.open_session(
        mcp_session_id="mcp-stable-key",
        api_key=api_key,
        server_name="postgres",
        client_info=ClientInfo(name="c2", version="2"),
    )
    assert first.data_key
    assert second.data_key == first.data_key
    assert second.id == first.id
    assert second.client_name == "c2"


async def test_memory_session_idle_ttl_closes() -> None:
    store: MemorySessionService = MemorySessionService(idle_ttl_seconds=60)
    api_key = await store.authenticate(DEV_API_KEY)
    assert api_key is not None
    await store.open_session(
        mcp_session_id="mcp-idle",
        api_key=api_key,
        server_name="postgres",
        client_info=ClientInfo(name="c", version="1"),
    )
    store.backdate_last_seen("mcp-idle", seconds_ago=120)
    assert await store.touch("mcp-idle") is None
    assert await store.touch("mcp-idle") is None


async def test_memory_session_close() -> None:
    store: MemorySessionService = MemorySessionService()
    api_key = await store.authenticate(DEV_API_KEY)
    assert api_key is not None
    await store.open_session(
        mcp_session_id="mcp-close",
        api_key=api_key,
        server_name="postgres",
        client_info=ClientInfo(),
    )
    assert await store.close_session("mcp-close") is True
    assert await store.touch("mcp-close") is None
    assert await store.close_session("mcp-close") is False


async def test_memory_session_get_session() -> None:
    store: MemorySessionService = MemorySessionService()
    api_key = await store.authenticate(DEV_API_KEY)
    assert api_key is not None
    opened = await store.open_session(
        mcp_session_id="mcp-get",
        api_key=api_key,
        server_name="postgres",
        client_info=ClientInfo(),
    )
    fetched = await store.get_session("mcp-get")
    assert fetched is not None
    assert fetched.id == opened.id
    assert fetched.data_key == opened.data_key
    assert await store.get_session("missing") is None
    await store.close_session("mcp-get")
    assert await store.get_session("mcp-get") is None


def test_bind_session_stamps_contextvars() -> None:
    assert session_id_var.get() == NO_SESSION
    session_uuid: UUID = UUID("00000000-0000-4000-8000-000000000099")
    with bind_session(
        session_id=session_uuid,
        mcp_session_id="mcp-abc",
        api_key_name="local-dev",
    ):
        assert session_id_var.get() == str(session_uuid)
        assert mcp_session_id_var.get() == "mcp-abc"
        assert api_key_name_var.get() == "local-dev"
    assert session_id_var.get() == NO_SESSION
