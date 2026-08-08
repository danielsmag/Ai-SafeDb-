"""Versioned API route registration (v1)."""

from fastapi import FastAPI

from app.domain.context import GatewayContext
from app.domain.routes.v1.client import register_client_routes
from app.domain.routes.v1.gateway import register_gateway_routes
from app.domain.routes.v1.manager import register_manager_v1_routes
from app.domain.routes.v1.sessions import register_session_routes


def register_v1_routes(api: FastAPI, ctx: GatewayContext) -> None:
    """Attach all `/api/v1` route groups."""
    register_gateway_routes(api, ctx)
    register_manager_v1_routes(api, ctx)
    if ctx.session_store is not None:
        register_session_routes(api, ctx)
        register_client_routes(api, ctx)
