"""Client UI session listing routes."""

from uuid import UUID

from fastapi import FastAPI, Request

from app.connectors.models import SessionRecord, User
from app.domain.context import GatewayContext
from app.domain.dependencies import require_user_session
from app.domain.paths import CLIENT_API_PREFIX
from app.schemas import SessionListResponse, SessionSummaryResponse
from app.services.session import SessionStore


def register_client_session_routes(api: FastAPI, ctx: GatewayContext) -> None:
    store: SessionStore | None = ctx.session_store
    if store is None:
        return

    @api.get(
        f"{CLIENT_API_PREFIX}/sessions",
        response_model=SessionListResponse,
        tags=["client-ui"],
    )
    async def list_sessions(request: Request) -> SessionListResponse:
        user: User = await require_user_session(
            ctx.settings, ctx.auth_store, request
        )
        api_key_ids: list[UUID] = await store.list_api_key_ids_for_user(user.id)
        sessions: list[SessionRecord] = await store.list_sessions(api_key_ids)
        return SessionListResponse(
            sessions=[
                SessionSummaryResponse.from_record(session) for session in sessions
            ]
        )
