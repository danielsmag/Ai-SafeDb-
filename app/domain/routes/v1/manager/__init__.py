"""Register manager UI v1 routes."""

from fastapi import FastAPI

from app.domain.context import GatewayContext
from app.domain.routes.v1.manager.admin import register_manager_routes
from app.domain.routes.v1.manager.auth import register_manager_auth_routes
from app.domain.routes.v1.manager.pipelines import register_manager_pipeline_routes


def register_manager_v1_routes(api: FastAPI, ctx: GatewayContext) -> None:
    register_manager_pipeline_routes(api, ctx)
    if ctx.session_store is None:
        return
    register_manager_auth_routes(api, ctx)
    register_manager_routes(api, ctx)
