"""Register all gateway HTTP routes on a FastAPI application."""

from fastapi import FastAPI

from app.domain.context import GatewayContext
from app.domain.routes.v1 import register_v1_routes


def register_routes(api: FastAPI, ctx: GatewayContext) -> None:
    """Attach every gateway route group to ``api``."""
    register_v1_routes(api, ctx)
