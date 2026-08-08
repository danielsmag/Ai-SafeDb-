"""Manager console routes (users, policies, workflows, history, sessions)."""

from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query, Request

from app.connectors.models import SessionRecord, User
from app.domain.context import GatewayContext
from app.domain.dependencies import require_admin_session
from app.domain.paths import MANAGER_API_PREFIX
from app.models import McpServerConfig
from app.schemas import (
    CreateUserRequest,
    PolicyListResponse,
    PolicySummary,
    SessionListResponse,
    SessionSummaryResponse,
    UpdateUserRequest,
    UserListResponse,
    UserResponse,
    WorkflowListResponse,
    WorkflowSummaryResponse,
)
from app.services.auth import AuthStore
from app.services.history import (
    HistoryFacets,
    HistoryStore,
    ToolCallHistory,
    ToolCallHistoryPage,
)
from app.services.session import SessionStore
from app.services.workflows import build_workflow_summary


def register_manager_routes(api: FastAPI, ctx: GatewayContext) -> None:
    history_store: HistoryStore | None = ctx.history_store
    store: SessionStore | None = ctx.session_store
    auth_store: AuthStore | None = ctx.auth_store
    if history_store is None or store is None:
        return

    @api.get(
        f"{MANAGER_API_PREFIX}/users",
        response_model=UserListResponse,
        tags=["manager-ui"],
    )
    async def admin_list_users(request: Request) -> UserListResponse:
        await require_admin_session(ctx.settings, auth_store, request)
        assert auth_store is not None
        users: list[User] = await auth_store.list_users()
        return UserListResponse(
            users=[
                UserResponse(
                    id=u.id,
                    username=u.username,
                    is_admin=u.is_admin,
                    created_at=u.created_at,
                    disabled_at=u.disabled_at,
                )
                for u in users
            ]
        )

    @api.post(
        f"{MANAGER_API_PREFIX}/users",
        response_model=UserResponse,
        status_code=201,
        tags=["manager-ui"],
    )
    async def admin_create_user(
        payload: CreateUserRequest,
        request: Request,
    ) -> UserResponse:
        await require_admin_session(ctx.settings, auth_store, request)
        assert auth_store is not None
        try:
            user: User = await auth_store.create_user(
                payload.username,
                payload.password,
                payload.is_admin,
            )
        except Exception as err:
            if "unique" in str(err).lower():
                raise HTTPException(
                    status_code=409,
                    detail="username already exists",
                ) from err
            raise
        return UserResponse(
            id=user.id,
            username=user.username,
            is_admin=user.is_admin,
            created_at=user.created_at,
            disabled_at=user.disabled_at,
        )

    @api.patch(
        f"{MANAGER_API_PREFIX}/users/{{user_id}}",
        response_model=UserResponse,
        tags=["manager-ui"],
    )
    async def admin_update_user(
        user_id: UUID,
        payload: UpdateUserRequest,
        request: Request,
    ) -> UserResponse:
        await require_admin_session(ctx.settings, auth_store, request)
        assert auth_store is not None
        user: User | None = await auth_store.update_user(
            user_id,
            password=payload.password,
            is_admin=payload.is_admin,
            disabled=payload.disabled,
        )
        if user is None:
            raise HTTPException(
                status_code=404,
                detail="user not found",
            )
        return UserResponse(
            id=user.id,
            username=user.username,
            is_admin=user.is_admin,
            created_at=user.created_at,
            disabled_at=user.disabled_at,
        )

    @api.get(
        f"{MANAGER_API_PREFIX}/policies",
        response_model=PolicyListResponse,
        tags=["manager-ui"],
    )
    async def admin_list_policies(request: Request) -> PolicyListResponse:
        await require_admin_session(ctx.settings, auth_store, request)
        summaries: list[PolicySummary] = []
        for policy in ctx.policies.values():
            pii_count: int = sum(len(table.pii) for table in policy.access.tables)
            summaries.append(
                PolicySummary(
                    name=policy.name,
                    type=policy.type,
                    dialect=policy.dialect,
                    read_only=policy.read_only,
                    denied_keywords=policy.denied_keywords,
                    tables_count=len(policy.access.tables),
                    pii_rules_count=pii_count,
                )
            )
        return PolicyListResponse(policies=summaries)

    @api.get(
        f"{MANAGER_API_PREFIX}/workflows",
        response_model=WorkflowListResponse,
        tags=["manager-ui"],
    )
    async def admin_list_workflows(request: Request) -> WorkflowListResponse:
        await require_admin_session(ctx.settings, auth_store, request)
        configs_by_name: dict[str, McpServerConfig] = {
            config.name: config for config in ctx.configs
        }
        workflows: list[WorkflowSummaryResponse] = [
            build_workflow_summary(
                workflow,
                ctx.workflow_catalog,
                configs_by_name,
                ctx.policies,
            )
            for workflow in ctx.workflow_catalog.workflows.values()
        ]
        return WorkflowListResponse(workflows=workflows)

    @api.get(
        f"{MANAGER_API_PREFIX}/history",
        response_model=ToolCallHistoryPage,
        tags=["manager-ui"],
    )
    async def admin_list_history(
        request: Request,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        server: str | None = Query(default=None, min_length=1),
        session_id: UUID | None = None,
        user_id: UUID | None = None,
        tool_name: Annotated[list[str] | None, Query()] = None,
        status: Annotated[list[str] | None, Query()] = None,
        api_key_id: Annotated[list[UUID] | None, Query()] = None,
        since: Annotated[datetime | None, Query()] = None,
        until: Annotated[datetime | None, Query()] = None,
        sort_by: str | None = Query(default=None),
        sort_order: str | None = Query(default=None),
    ) -> ToolCallHistoryPage:
        await require_admin_session(ctx.settings, auth_store, request)
        return await history_store.list_all_calls(
            limit=limit,
            offset=offset,
            server=server,
            session_id=session_id,
            user_id=user_id,
            tool_names=tool_name,
            statuses=status,
            api_key_ids=api_key_id,
            since=since,
            until=until,
            sort_by=sort_by,
            sort_order=sort_order,
        )

    @api.get(
        f"{MANAGER_API_PREFIX}/history/facets",
        response_model=HistoryFacets,
        tags=["manager-ui"],
    )
    async def admin_history_facets(request: Request) -> HistoryFacets:
        await require_admin_session(ctx.settings, auth_store, request)
        return await history_store.list_facets()

    @api.get(
        f"{MANAGER_API_PREFIX}/history/{{call_id}}",
        response_model=ToolCallHistory,
        tags=["manager-ui"],
    )
    async def admin_get_history_call(
        call_id: UUID,
        request: Request,
    ) -> ToolCallHistory:
        await require_admin_session(ctx.settings, auth_store, request)
        entry: ToolCallHistory | None = await history_store.get_call_admin(call_id)
        if entry is None:
            raise HTTPException(
                status_code=404,
                detail="unknown tool call",
            )
        return entry

    @api.get(
        f"{MANAGER_API_PREFIX}/sessions",
        response_model=SessionListResponse,
        tags=["manager-ui"],
    )
    async def admin_list_sessions(request: Request) -> SessionListResponse:
        await require_admin_session(ctx.settings, auth_store, request)
        sessions: list[SessionRecord] = await store.list_all_sessions()
        return SessionListResponse(
            sessions=[
                SessionSummaryResponse.from_record(session) for session in sessions
            ]
        )
