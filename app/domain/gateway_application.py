"""FastAPI application assembly for the MCP gateway."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path as FilePath
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, Header, HTTPException, Path, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastmcp import FastMCP
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.utilities.lifespan import combine_lifespans
from starlette.types import ASGIApp, Lifespan

from app import __version__
from app.connectors.models import ApiKey, SessionRecord, User, WebSession
from app.core.config import AppSettings
from app.core.database import Database
from app.core.logging import logger
from app.exceptions import GatewayError
from app.http import wrap_with_session_terminate
from app.models import McpServerConfig
from app.policies import Policy, PolicyLoader
from app.proxy_factory import ProxyFactory
from app.schemas import (
    CreateUserRequest,
    HealthResponse,
    LoginRequest,
    PolicyListResponse,
    PolicySummary,
    ServerListResponse,
    ServerSummary,
    SessionDataKeyResponse,
    SessionListResponse,
    SessionSummaryResponse,
    UpdateUserRequest,
    UserIdentityResponse,
    UserListResponse,
    UserResponse,
    WorkflowListResponse,
    WorkflowSummaryResponse,
)
from app.services.auth import AuthStore
from app.services.config_loader import ConfigLoader
from app.services.history import (
    HistoryFacets,
    HistoryStore,
    ToolCallHistory,
    ToolCallHistoryPage,
)
from app.services.session import SessionStore
from app.services.workflows import (
    WorkflowCatalog,
    WorkflowLoader,
    build_workflow_summary,
)


class GatewayApplication:
    """Assemble the API from settings and configured MCP servers."""

    def __init__(
        self,
        settings: AppSettings,
        loader: ConfigLoader,
        proxy_factory: ProxyFactory,
        policy_loader: PolicyLoader | None = None,
        database: Database | None = None,
        session_store: SessionStore | None = None,
        auth_store: AuthStore | None = None,
        history_store: HistoryStore | None = None,
        workflow_loader: WorkflowLoader | None = None,
    ) -> None:
        self._settings: AppSettings = settings
        self._loader: ConfigLoader = loader
        self._proxy_factory: ProxyFactory = proxy_factory
        self._policy_loader: PolicyLoader | None = policy_loader
        self._database: Database | None = database
        self._session_store: SessionStore | None = session_store
        self._auth_store: AuthStore | None = auth_store
        self._history_store: HistoryStore | None = history_store
        self._workflow_loader: WorkflowLoader | None = workflow_loader
        self._policies: dict[str, Policy] = {}
        self._workflow_catalog: WorkflowCatalog = WorkflowCatalog()

    def build(self) -> FastAPI:
        """Build and return the configured FastAPI application."""
        configs: list[McpServerConfig] = self._loader.load()
        self._policies = (
            self._policy_loader.load() if self._policy_loader is not None else {}
        )
        self._workflow_catalog = (
            self._workflow_loader.load()
            if self._workflow_loader is not None
            else WorkflowCatalog()
        )
        logger.info(
            "Loaded %d MCP server definition(s) from %s",
            len(configs),
            self._loader.config_dir,
        )

        mcp_apps: dict[str, StarletteWithLifespan] = {
            config.name: self._build_mcp_app(config) for config in configs
        }
        lifespans: list[Lifespan[FastAPI]] = []
        if (
            self._database is not None
            and self._session_store is not None
            and self._auth_store is not None
        ):
            lifespans.append(self._database_lifespan)
        lifespans.extend(mcp_app.lifespan for mcp_app in mcp_apps.values())
        lifespan: Lifespan[FastAPI] | None = (
            combine_lifespans(*lifespans) if lifespans else None
        )

        api: FastAPI = FastAPI(
            title="MCP Gateway",
            version=__version__,
            summary="Re-exposes YAML-defined MCP servers under a single HTTP origin.",
            lifespan=lifespan,
        )
        self._register_routes(api, configs)
        self._register_exception_handlers(api)

        for config in configs:
            mount_path: str = config.mount_path(self._settings.mount_prefix)
            mcp_app: StarletteWithLifespan = mcp_apps[config.name]
            mounted: ASGIApp = mcp_app
            if self._session_store is not None:
                mounted = wrap_with_session_terminate(mcp_app, self._session_store)
            api.mount(mount_path, mounted, name=f"mcp-{config.name}")
            logger.info("Exposing server %r at %s", config.name, mount_path)

        frontend_dist: FilePath = FilePath("frontend/dist")
        if frontend_dist.is_dir():
            api.mount(
                "/ui",
                StaticFiles(directory=frontend_dist, html=True),
                name="ui",
            )
            logger.info("Serving gateway UI from %s at /ui", frontend_dist)

        return api

    @asynccontextmanager
    async def _database_lifespan(self, _app: FastAPI) -> AsyncIterator[None]:
        assert self._database is not None
        assert self._session_store is not None
        assert self._auth_store is not None
        await self._database.open()
        try:
            await self._auth_store.ensure_schema()
            await self._session_store.ensure_schema()
            if self._history_store is not None:
                await self._history_store.ensure_schema()
            yield
        finally:
            await self._database.close()

    def _build_mcp_app(self, config: McpServerConfig) -> StarletteWithLifespan:
        policy: Policy | None = (
            self._policies.get(config.policy) if config.policy is not None else None
        )
        if config.policy is not None and policy is None:
            raise GatewayError(
                f"server {config.name!r} references unknown policy {config.policy!r}"
            )
        proxy: FastMCP = self._proxy_factory.create(config, policy)
        return proxy.http_app(
            path="/",
            stateless_http=self._settings.stateless_http,
            json_response=self._settings.json_response,
            allowed_hosts=self._settings.allowed_hosts or None,
            allowed_origins=self._settings.allowed_origins or None,
        )

    def _register_routes(self, api: FastAPI, configs: list[McpServerConfig]) -> None:
        summaries: list[ServerSummary] = [
            ServerSummary.from_config(config, url=self._public_url(config))
            for config in configs
        ]
        store: SessionStore | None = self._session_store
        auth_store: AuthStore | None = self._auth_store
        history_store: HistoryStore | None = self._history_store

        @api.get("/health", response_model=HealthResponse, tags=["gateway"])
        async def health() -> HealthResponse:
            return HealthResponse(
                status="ok", version=__version__, servers=len(summaries)
            )

        @api.get("/servers", response_model=ServerListResponse, tags=["gateway"])
        async def servers() -> ServerListResponse:
            return ServerListResponse(servers=summaries)

        if store is not None:

            @api.get(
                "/sessions/data-key",
                response_model=SessionDataKeyResponse,
                tags=["sessions"],
            )
            async def get_data_key_for_api_key(
                authorization: str | None = Header(default=None),
            ) -> SessionDataKeyResponse:
                api_key: ApiKey = await self._require_bearer_api_key(
                    store, authorization
                )
                session: SessionRecord | None = await store.get_latest_open_session(
                    api_key.id
                )
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

            if auth_store is not None:

                @api.post(
                    "/api/login",
                    response_model=UserIdentityResponse,
                    tags=["ui"],
                )
                async def login(
                    credentials: LoginRequest,
                    response: Response,
                ) -> UserIdentityResponse:
                    user: User | None = await auth_store.authenticate(
                        credentials.username, credentials.password
                    )
                    if user is None:
                        raise HTTPException(
                            status_code=401,
                            detail="invalid username or password",
                        )
                    created_session: tuple[WebSession, str] = (
                        await auth_store.create_session(user)
                    )
                    raw_token: str = created_session[1]
                    response.set_cookie(
                        key=self._settings.auth.cookie_name,
                        value=raw_token,
                        max_age=int(self._settings.auth.session_ttl_seconds),
                        httponly=True,
                        secure=self._settings.auth.cookie_secure,
                        samesite="lax",
                        path="/",
                    )
                    return UserIdentityResponse(
                        username=user.username,
                        is_admin=user.is_admin,
                        created_at=user.created_at,
                    )

                @api.post("/api/logout", status_code=204, tags=["ui"])
                async def logout(request: Request, response: Response) -> None:
                    raw_token: str | None = request.cookies.get(
                        self._settings.auth.cookie_name
                    )
                    if raw_token is not None:
                        await auth_store.revoke_session(raw_token)
                    response.delete_cookie(
                        key=self._settings.auth.cookie_name,
                        path="/",
                        secure=self._settings.auth.cookie_secure,
                        httponly=True,
                        samesite="lax",
                    )

            @api.get(
                "/api/me",
                response_model=UserIdentityResponse,
                tags=["ui"],
            )
            async def get_identity(
                request: Request,
            ) -> UserIdentityResponse:
                user: User = await self._require_user_session(
                    auth_store, request
                )
                return UserIdentityResponse(
                    username=user.username,
                    is_admin=user.is_admin,
                    created_at=user.created_at,
                )

            @api.get(
                "/api/sessions",
                response_model=SessionListResponse,
                tags=["ui"],
            )
            async def list_sessions(
                request: Request,
            ) -> SessionListResponse:
                user: User = await self._require_user_session(
                    auth_store, request
                )
                api_key_ids: list[UUID] = await store.list_api_key_ids_for_user(
                    user.id
                )
                sessions: list[SessionRecord] = await store.list_sessions(api_key_ids)
                return SessionListResponse(
                    sessions=[
                        SessionSummaryResponse.from_record(session)
                        for session in sessions
                    ]
                )

            if history_store is not None:

                @api.get(
                    "/api/history",
                    response_model=ToolCallHistoryPage,
                    tags=["ui"],
                )
                async def list_history(
                    request: Request,
                    limit: int = Query(default=25, ge=1, le=100),
                    offset: int = Query(default=0, ge=0),
                    server: str | None = Query(default=None, min_length=1),
                    session_id: UUID | None = None,
                ) -> ToolCallHistoryPage:
                    user: User = await self._require_user_session(
                        auth_store, request
                    )
                    api_key_ids: list[UUID] = (
                        await store.list_api_key_ids_for_user(user.id)
                    )
                    return await history_store.list_calls(
                        api_key_ids,
                        limit=limit,
                        offset=offset,
                        server=server,
                        session_id=session_id,
                    )

                @api.get(
                    "/api/history/{call_id}",
                    response_model=ToolCallHistory,
                    tags=["ui"],
                )
                async def get_history_call(
                    call_id: UUID,
                    request: Request,
                ) -> ToolCallHistory:
                    user: User = await self._require_user_session(
                        auth_store, request
                    )
                    api_key_ids: list[UUID] = (
                        await store.list_api_key_ids_for_user(user.id)
                    )
                    entry: ToolCallHistory | None = await history_store.get_call(
                        api_key_ids, call_id
                    )
                    if entry is None:
                        raise HTTPException(
                            status_code=404,
                            detail="unknown tool call",
                        )
                    return entry

                @api.get(
                    "/api/admin/users",
                    response_model=UserListResponse,
                    tags=["admin"],
                )
                async def admin_list_users(
                    request: Request,
                ) -> UserListResponse:
                    await self._require_admin_session(auth_store, request)
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
                    "/api/admin/users",
                    response_model=UserResponse,
                    status_code=201,
                    tags=["admin"],
                )
                async def admin_create_user(
                    payload: CreateUserRequest,
                    request: Request,
                ) -> UserResponse:
                    await self._require_admin_session(auth_store, request)
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
                    "/api/admin/users/{user_id}",
                    response_model=UserResponse,
                    tags=["admin"],
                )
                async def admin_update_user(
                    user_id: UUID,
                    payload: UpdateUserRequest,
                    request: Request,
                ) -> UserResponse:
                    await self._require_admin_session(auth_store, request)
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
                    "/api/admin/policies",
                    response_model=PolicyListResponse,
                    tags=["admin"],
                )
                async def admin_list_policies(
                    request: Request,
                ) -> PolicyListResponse:
                    await self._require_admin_session(auth_store, request)
                    summaries: list[PolicySummary] = []
                    for policy in self._policies.values():
                        pii_count: int = sum(
                            len(table.pii) for table in policy.access.tables
                        )
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
                    "/api/admin/workflows",
                    response_model=WorkflowListResponse,
                    tags=["admin"],
                )
                async def admin_list_workflows(
                    request: Request,
                ) -> WorkflowListResponse:
                    await self._require_admin_session(auth_store, request)
                    configs_by_name: dict[str, McpServerConfig] = {
                        config.name: config for config in configs
                    }
                    workflows: list[WorkflowSummaryResponse] = [
                        build_workflow_summary(
                            workflow,
                            self._workflow_catalog,
                            configs_by_name,
                            self._policies,
                        )
                        for workflow in self._workflow_catalog.workflows.values()
                    ]
                    return WorkflowListResponse(workflows=workflows)

                @api.get(
                    "/api/admin/history",
                    response_model=ToolCallHistoryPage,
                    tags=["admin"],
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
                    await self._require_admin_session(auth_store, request)
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
                    "/api/admin/history/facets",
                    response_model=HistoryFacets,
                    tags=["admin"],
                )
                async def admin_history_facets(
                    request: Request,
                ) -> HistoryFacets:
                    await self._require_admin_session(auth_store, request)
                    return await history_store.list_facets()

                @api.get(
                    "/api/admin/history/{call_id}",
                    response_model=ToolCallHistory,
                    tags=["admin"],
                )
                async def admin_get_history_call(
                    call_id: UUID,
                    request: Request,
                ) -> ToolCallHistory:
                    await self._require_admin_session(auth_store, request)
                    entry: ToolCallHistory | None = (
                        await history_store.get_call_admin(call_id)
                    )
                    if entry is None:
                        raise HTTPException(
                            status_code=404,
                            detail="unknown tool call",
                        )
                    return entry

                @api.get(
                    "/api/admin/sessions",
                    response_model=SessionListResponse,
                    tags=["admin"],
                )
                async def admin_list_sessions(
                    request: Request,
                ) -> SessionListResponse:
                    await self._require_admin_session(auth_store, request)
                    sessions: list[SessionRecord] = await store.list_all_sessions()
                    return SessionListResponse(
                        sessions=[
                            SessionSummaryResponse.from_record(session)
                            for session in sessions
                        ]
                    )

            @api.get(
                "/sessions/{mcp_session_id}/data-key",
                response_model=SessionDataKeyResponse,
                tags=["sessions"],
            )
            async def get_session_data_key(
                mcp_session_id: str = Path(min_length=1),
                authorization: str | None = Header(default=None),
            ) -> SessionDataKeyResponse:
                api_key: ApiKey = await self._require_bearer_api_key(
                    store, authorization
                )
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

    async def _require_user_session(
        self,
        auth_store: AuthStore | None,
        request: Request,
    ) -> User:
        if auth_store is None:
            raise HTTPException(
                status_code=503,
                detail="web authentication unavailable",
            )
        raw_token: str | None = request.cookies.get(
            self._settings.auth.cookie_name
        )
        if raw_token is None:
            raise HTTPException(status_code=401, detail="not authenticated")
        user: User | None = await auth_store.resolve_session(raw_token)
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="session is invalid or expired",
            )
        return user

    async def _require_admin_session(
        self,
        auth_store: AuthStore | None,
        request: Request,
    ) -> User:
        user: User = await self._require_user_session(auth_store, request)
        if not user.is_admin:
            raise HTTPException(
                status_code=403,
                detail="administrator access required",
            )
        return user

    async def _require_bearer_api_key(
        self,
        store: SessionStore,
        authorization: str | None,
    ) -> ApiKey:
        if authorization is None:
            raise HTTPException(
                status_code=401,
                detail="missing Authorization header",
            )
        parts: list[str] = authorization.split(" ", maxsplit=1)
        if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
            raise HTTPException(
                status_code=401,
                detail="Authorization header must be Bearer <api_key>",
            )
        raw_key: str = parts[1].strip()
        api_key: ApiKey | None = await store.authenticate(raw_key)
        if api_key is None:
            raise HTTPException(
                status_code=401,
                detail="invalid or revoked API key",
            )
        return api_key

    def _register_exception_handlers(self, api: FastAPI) -> None:
        @api.exception_handler(GatewayError)
        async def handle_gateway_error(
            request: Request, exc: GatewayError
        ) -> JSONResponse:
            logger.error("Gateway error on %s: %s", request.url.path, exc)
            return JSONResponse(status_code=500, content={"detail": str(exc)})

    def _public_url(self, config: McpServerConfig) -> str:
        return (
            f"{self._settings.public_base_url}"
            f"{config.mount_path(self._settings.mount_prefix)}"
        )
