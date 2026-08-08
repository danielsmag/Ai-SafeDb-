"""FastAPI application assembly for the MCP gateway."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path as FilePath

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.utilities.lifespan import combine_lifespans
from starlette.types import ASGIApp, Lifespan

from app import __version__
from app.core.config import AppSettings
from app.core.database import Database
from app.core.logging import logger
from app.domain.context import GatewayContext
from app.domain.mcp import build_mcp_app, public_url
from app.domain.paths import CLIENT_UI_PREFIX, MANAGER_UI_PREFIX
from app.domain.routes import register_routes
from app.exceptions import GatewayError
from app.http import wrap_with_session_terminate
from app.models import McpServerConfig
from app.policies import Policy, PolicyLoader
from app.proxy_factory import ProxyFactory
from app.schemas import ServerSummary
from app.services.auth import AuthStore
from app.services.config_loader import ConfigLoader
from app.services.guard import GuardService
from app.services.history import HistoryStore
from app.services.pipelines import (
    PipelineCatalog,
    PipelineExecutor,
    PipelineLoader,
    PipelineService,
)
from app.services.session import SessionStore
from app.services.workflows import WorkflowCatalog, WorkflowLoader


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
        pipeline_loader: PipelineLoader | None = None,
        pipeline_executor: PipelineExecutor | None = None,
        guard_service: GuardService | None = None,
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
        self._pipeline_loader: PipelineLoader | None = pipeline_loader
        self._pipeline_executor: PipelineExecutor | None = pipeline_executor
        self._guard_service: GuardService | None = guard_service
        self._pipeline_service: PipelineService | None = None
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
        pipeline_catalog: PipelineCatalog = (
            self._pipeline_loader.load()
            if self._pipeline_loader is not None
            else PipelineCatalog()
        )
        configs_by_name: dict[str, McpServerConfig] = {
            config.name: config for config in configs
        }
        self._pipeline_service = (
            PipelineService(
                catalog=pipeline_catalog,
                executor=self._pipeline_executor,
                mcp_servers=configs_by_name,
                policies=self._policies,
                guard_service=self._guard_service,
            )
            if self._pipeline_executor is not None
            else None
        )
        logger.info(
            "Loaded %d MCP server definition(s) from %s",
            len(configs),
            self._loader.config_dir,
        )

        mcp_apps: dict[str, StarletteWithLifespan] = {
            config.name: build_mcp_app(
                self._settings,
                self._proxy_factory,
                config,
                self._policies,
            )
            for config in configs
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
        summaries: list[ServerSummary] = [
            ServerSummary.from_config(config, url=public_url(self._settings, config))
            for config in configs
        ]
        ctx: GatewayContext = GatewayContext(
            settings=self._settings,
            session_store=self._session_store,
            auth_store=self._auth_store,
            history_store=self._history_store,
            pipeline_service=self._pipeline_service,
            policies=self._policies,
            workflow_catalog=self._workflow_catalog,
            configs=configs,
            server_summaries=summaries,
        )
        register_routes(api, ctx)
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
            static_files: StaticFiles = StaticFiles(
                directory=frontend_dist,
                html=True,
            )
            api.mount(CLIENT_UI_PREFIX, static_files, name="ui-client")
            api.mount(MANAGER_UI_PREFIX, static_files, name="ui-manager")
            logger.info(
                "Serving client UI at %s and manager UI at %s from %s",
                CLIENT_UI_PREFIX,
                MANAGER_UI_PREFIX,
                frontend_dist,
            )

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

    def _register_exception_handlers(self, api: FastAPI) -> None:
        @api.exception_handler(GatewayError)
        async def handle_gateway_error(
            request: Request, exc: GatewayError
        ) -> JSONResponse:
            logger.error("Gateway error on %s: %s", request.url.path, exc)
            return JSONResponse(status_code=500, content={"detail": str(exc)})
