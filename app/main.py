"""Composition root: build the FastAPI app that fronts every configured MCP server."""

import logging

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastmcp.server.http import StarletteWithLifespan
from fastmcp.utilities.lifespan import combine_lifespans
from starlette.types import Lifespan

from app import __version__
from app.config_loader import ConfigLoader
from app.exceptions import GatewayError
from app.models import McpServerConfig
from app.proxy_factory import ProxyFactory
from app.schemas import HealthResponse, ServerListResponse, ServerSummary
from app.settings import AppSettings

logger = logging.getLogger(__name__)


class GatewayApplication:
    """Assembles the FastAPI application from the loaded server definitions."""

    def __init__(
        self,
        settings: AppSettings,
        loader: ConfigLoader,
        proxy_factory: ProxyFactory,
    ) -> None:
        self._settings = settings
        self._loader = loader
        self._proxy_factory = proxy_factory

    def build(self) -> FastAPI:
        configs = self._loader.load()
        logger.info(
            "Loaded %d MCP server definition(s) from %s",
            len(configs),
            self._loader.config_dir,
        )

        mcp_apps = {config.name: self._build_mcp_app(config) for config in configs}
        lifespan: Lifespan[FastAPI] | None = (
            combine_lifespans(*(mcp_app.lifespan for mcp_app in mcp_apps.values()))
            if mcp_apps
            else None
        )

        api = FastAPI(
            title="MCP Gateway",
            version=__version__,
            summary="Re-exposes YAML-defined MCP servers under a single HTTP origin.",
            lifespan=lifespan,
        )
        self._register_routes(api, configs)
        self._register_exception_handlers(api)

        for config in configs:
            mount_path = config.mount_path(self._settings.mount_prefix)
            api.mount(mount_path, mcp_apps[config.name], name=f"mcp-{config.name}")
            logger.info("Exposing server %r at %s", config.name, mount_path)

        return api

    def _build_mcp_app(self, config: McpServerConfig) -> StarletteWithLifespan:
        proxy = self._proxy_factory.create(config)
        return proxy.http_app(
            path="/",
            stateless_http=self._settings.stateless_http,
            json_response=self._settings.json_response,
            allowed_hosts=self._settings.allowed_hosts or None,
            allowed_origins=self._settings.allowed_origins or None,
        )

    def _register_routes(self, api: FastAPI, configs: list[McpServerConfig]) -> None:
        summaries = [
            ServerSummary.from_config(config, url=self._public_url(config))
            for config in configs
        ]

        @api.get("/health", response_model=HealthResponse, tags=["gateway"])
        async def health() -> HealthResponse:
            return HealthResponse(
                status="ok", version=__version__, servers=len(summaries)
            )

        @api.get("/servers", response_model=ServerListResponse, tags=["gateway"])
        async def servers() -> ServerListResponse:
            return ServerListResponse(servers=summaries)

    def _register_exception_handlers(self, api: FastAPI) -> None:
        @api.exception_handler(GatewayError)
        async def handle_gateway_error(
            request: Request, exc: GatewayError
        ) -> JSONResponse:
            logger.error("Gateway error on %s: %s", request.url.path, exc)
            return JSONResponse(status_code=500, content={"detail": str(exc)})

    def _public_url(self, config: McpServerConfig) -> str:
        base = self._settings.public_base_url
        return f"{base}{config.mount_path(self._settings.mount_prefix)}"


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Entry point for `uvicorn app.main:create_app --factory` and for tests."""
    settings = settings or AppSettings()
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    gateway = GatewayApplication(
        settings=settings,
        loader=ConfigLoader(settings.config_dir),
        proxy_factory=ProxyFactory(),
    )
    return gateway.build()
