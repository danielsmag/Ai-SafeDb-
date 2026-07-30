"""Uvicorn entry point for the MCP gateway."""

from fastapi import FastAPI

from app.core.bootstrap import bootstrap_application
from app.core.config import AppSettings
from app.domain.gateway_application import GatewayApplication

__all__: list[str] = ["GatewayApplication", "create_app"]


def create_app(settings: AppSettings | None = None) -> FastAPI:
    """Entry point for `uvicorn app.main:create_app --factory` and for tests."""
    return bootstrap_application(settings)
