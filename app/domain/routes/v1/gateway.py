"""Core gateway discovery routes (health, server list)."""

from fastapi import FastAPI

from app import __version__
from app.domain.context import GatewayContext
from app.domain.paths import API_V1_PREFIX
from app.schemas import HealthResponse, ServerListResponse, ServerSummary


def register_gateway_routes(api: FastAPI, ctx: GatewayContext) -> None:
    summaries: list[ServerSummary] = ctx.server_summaries

    @api.get(f"{API_V1_PREFIX}/health", response_model=HealthResponse, tags=["gateway"])
    async def health() -> HealthResponse:
        return HealthResponse(
            status="ok", version=__version__, servers=len(summaries)
        )

    @api.get(
        f"{API_V1_PREFIX}/servers",
        response_model=ServerListResponse,
        tags=["gateway"],
    )
    async def servers() -> ServerListResponse:
        return ServerListResponse(servers=summaries)
