"""Manager UI pipeline execution and inspection routes."""

from uuid import UUID

from fastapi import FastAPI, HTTPException, Request

from app.domain.context import GatewayContext
from app.domain.dependencies import require_admin_session
from app.domain.paths import MANAGER_API_PREFIX
from app.services.pipelines import (
    PipelineListResponse,
    PipelineResult,
    PipelineRunRequest,
    PipelineService,
)


def register_manager_pipeline_routes(api: FastAPI, ctx: GatewayContext) -> None:
    pipeline_service: PipelineService | None = ctx.pipeline_service
    if pipeline_service is None:
        return

    @api.get(
        f"{MANAGER_API_PREFIX}/pipelines",
        response_model=PipelineListResponse,
        tags=["manager-ui"],
    )
    async def manager_list_pipelines(request: Request) -> PipelineListResponse:
        await require_admin_session(ctx.settings, ctx.auth_store, request)
        return PipelineListResponse(pipelines=pipeline_service.list_pipelines())

    @api.post(
        f"{MANAGER_API_PREFIX}/pipelines/{{pipeline_name}}/runs",
        response_model=PipelineResult,
        status_code=202,
        tags=["manager-ui"],
    )
    async def manager_start_pipeline(
        pipeline_name: str,
        payload: PipelineRunRequest,
        request: Request,
    ) -> PipelineResult:
        await require_admin_session(ctx.settings, ctx.auth_store, request)
        if not pipeline_service.has_pipeline(pipeline_name):
            raise HTTPException(status_code=404, detail="unknown pipeline")
        return pipeline_service.start(pipeline_name, payload.inputs)

    @api.get(
        f"{MANAGER_API_PREFIX}/pipeline-runs/{{run_id}}",
        response_model=PipelineResult,
        tags=["manager-ui"],
    )
    async def manager_get_pipeline_run(
        run_id: UUID,
        request: Request,
    ) -> PipelineResult:
        await require_admin_session(ctx.settings, ctx.auth_store, request)
        run: PipelineResult | None = pipeline_service.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="unknown pipeline run")
        return run

    @api.post(
        f"{MANAGER_API_PREFIX}/pipeline-runs/{{run_id}}/cancel",
        response_model=PipelineResult,
        tags=["manager-ui"],
    )
    async def manager_cancel_pipeline_run(
        run_id: UUID,
        request: Request,
    ) -> PipelineResult:
        await require_admin_session(ctx.settings, ctx.auth_store, request)
        run: PipelineResult | None = pipeline_service.cancel(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="unknown pipeline run")
        return run
