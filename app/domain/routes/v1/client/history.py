"""Client UI tool-call history routes."""

from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request

from app.connectors.models import User
from app.domain.context import GatewayContext
from app.domain.dependencies import require_user_session
from app.domain.paths import CLIENT_API_PREFIX
from app.services.history import HistoryStore, ToolCallHistory, ToolCallHistoryPage
from app.services.session import SessionStore


def register_client_history_routes(api: FastAPI, ctx: GatewayContext) -> None:
    history_store: HistoryStore | None = ctx.history_store
    store: SessionStore | None = ctx.session_store
    if history_store is None or store is None:
        return

    @api.get(
        f"{CLIENT_API_PREFIX}/history",
        response_model=ToolCallHistoryPage,
        tags=["client-ui"],
    )
    async def list_history(
        request: Request,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        server: str | None = Query(default=None, min_length=1),
        session_id: UUID | None = None,
    ) -> ToolCallHistoryPage:
        user: User = await require_user_session(
            ctx.settings, ctx.auth_store, request
        )
        api_key_ids: list[UUID] = await store.list_api_key_ids_for_user(user.id)
        return await history_store.list_calls(
            api_key_ids,
            limit=limit,
            offset=offset,
            server=server,
            session_id=session_id,
        )

    @api.get(
        f"{CLIENT_API_PREFIX}/history/{{call_id}}",
        response_model=ToolCallHistory,
        tags=["client-ui"],
    )
    async def get_history_call(
        call_id: UUID,
        request: Request,
    ) -> ToolCallHistory:
        user: User = await require_user_session(
            ctx.settings, ctx.auth_store, request
        )
        api_key_ids: list[UUID] = await store.list_api_key_ids_for_user(user.id)
        entry: ToolCallHistory | None = await history_store.get_call(
            api_key_ids, call_id
        )
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail="unknown tool call",
            )
        return entry
