"""MCP session data-key routes under `/api/v1/sessions`."""

from fastapi import FastAPI, Header, HTTPException, Path

from app.connectors.models import ApiKey, SessionRecord
from app.domain.context import GatewayContext
from app.domain.dependencies import require_bearer_api_key
from app.domain.paths import API_V1_PREFIX
from app.schemas import SessionDataKeyResponse
from app.services.session import SessionStore


def register_session_routes(api: FastAPI, ctx: GatewayContext) -> None:
    store: SessionStore | None = ctx.session_store
    if store is None:
        return

    @api.get(
        f"{API_V1_PREFIX}/sessions/data-key",
        response_model=SessionDataKeyResponse,
        tags=["sessions"],
    )
    async def get_data_key_for_api_key(
        authorization: str | None = Header(default=None),
    ) -> SessionDataKeyResponse:
        api_key: ApiKey = await require_bearer_api_key(store, authorization)
        session: SessionRecord | None = await store.get_latest_open_session(api_key.id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail="no open session for this API key",
            )
        return SessionDataKeyResponse(
            session_id=session.id,
            mcp_session_id=session.mcp_session_id,
            data_key=session.data_key,
        )

    @api.get(
        f"{API_V1_PREFIX}/sessions/{{mcp_session_id}}/data-key",
        response_model=SessionDataKeyResponse,
        tags=["sessions"],
    )
    async def get_session_data_key(
        mcp_session_id: str = Path(min_length=1),
        authorization: str | None = Header(default=None),
    ) -> SessionDataKeyResponse:
        api_key: ApiKey = await require_bearer_api_key(store, authorization)
        session: SessionRecord | None = await store.get_session(mcp_session_id)
        if session is None:
            raise HTTPException(
                status_code=404,
                detail="unknown or closed MCP session",
            )
        if session.api_key_id != api_key.id:
            raise HTTPException(
                status_code=403,
                detail="API key does not own this session",
            )
        return SessionDataKeyResponse(
            session_id=session.id,
            mcp_session_id=session.mcp_session_id,
            data_key=session.data_key,
        )
