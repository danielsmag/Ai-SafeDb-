"""Register client UI v1 routes."""

from fastapi import FastAPI

from app.domain.context import GatewayContext
from app.domain.routes.v1.client.auth import register_client_auth_routes
from app.domain.routes.v1.client.history import register_client_history_routes
from app.domain.routes.v1.client.sessions import register_client_session_routes


def register_client_routes(api: FastAPI, ctx: GatewayContext) -> None:
    register_client_auth_routes(api, ctx)
    register_client_session_routes(api, ctx)
    register_client_history_routes(api, ctx)
