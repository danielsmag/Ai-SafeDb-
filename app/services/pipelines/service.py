"""Pipeline catalog presentation and in-memory run lifecycle management."""

import asyncio
from uuid import UUID, uuid4

import yaml

from app.models import McpServerConfig
from app.policies import Policy
from app.services.guard import GuardService
from app.services.pipelines.context import ExecutionContext
from app.services.pipelines.executor import PipelineExecutor
from app.services.pipelines.models import (
    JsonValue,
    PipelineCatalog,
    PipelineDefinition,
    PipelineEdgeResponse,
    PipelineGraphResponse,
    PipelineNodeResponse,
    PipelineResult,
    PipelineSummaryResponse,
)


class PipelineService:
    """Expose pipeline graphs and control asynchronous executions."""

    def __init__(
        self,
        catalog: PipelineCatalog,
        executor: PipelineExecutor,
        mcp_servers: dict[str, McpServerConfig],
        policies: dict[str, Policy],
        guard_service: GuardService | None = None,
    ) -> None:
        self._catalog: PipelineCatalog = catalog
        self._executor: PipelineExecutor = executor
        self._mcp_servers: dict[str, McpServerConfig] = mcp_servers
        self._policies: dict[str, Policy] = policies
        self._guard_service: GuardService | None = guard_service
        self._runs: dict[UUID, PipelineResult] = {}
        self._running_tasks: dict[UUID, asyncio.Task[PipelineResult]] = {}
        self._latest_runs: dict[str, UUID] = {}

    def list_pipelines(self) -> list[PipelineSummaryResponse]:
        """Return renderable summaries for all configured pipelines."""
        return [
            self._build_summary(pipeline)
            for pipeline in self._catalog.pipelines.values()
        ]

    def has_pipeline(self, name: str) -> bool:
        """Return whether a pipeline is configured."""
        return name in self._catalog.pipelines

    def start(
        self,
        name: str,
        inputs: dict[str, JsonValue] | None = None,
    ) -> PipelineResult:
        """Start a background pipeline run and return its initial snapshot."""
        pipeline: PipelineDefinition = self._catalog.pipelines[name]
        run: PipelineResult = PipelineResult(
            run_id=uuid4(),
            pipeline_name=name,
            status="pending",
        )
        context: ExecutionContext = ExecutionContext(
            inputs=inputs or {},
            mcp_servers=self._mcp_servers,
            policies=self._policies,
            guard_service=self._guard_service,
        )
        task: asyncio.Task[PipelineResult] = asyncio.create_task(
            self._executor.execute(pipeline, context, run),
            name=f"pipeline:{name}:{run.run_id}",
        )
        self._runs[run.run_id] = run
        self._running_tasks[run.run_id] = task
        self._latest_runs[name] = run.run_id
        task.add_done_callback(
            lambda completed, run_id=run.run_id: self._complete_run(run_id, completed)
        )
        return run

    def get_run(self, run_id: UUID) -> PipelineResult | None:
        """Return a run snapshot by identifier."""
        return self._runs.get(run_id)

    def cancel(self, run_id: UUID) -> PipelineResult | None:
        """Request cancellation of a running pipeline."""
        run: PipelineResult | None = self._runs.get(run_id)
        task: asyncio.Task[PipelineResult] | None = self._running_tasks.get(run_id)
        if run is None:
            return None
        if task is not None and not task.done():
            task.cancel()
        return run

    def _complete_run(
        self,
        run_id: UUID,
        completed: asyncio.Task[PipelineResult],
    ) -> None:
        self._running_tasks.pop(run_id, None)
        if completed.cancelled():
            return
        error: BaseException | None = completed.exception()
        if error is not None:
            run: PipelineResult = self._runs[run_id]
            run.status = "failed"
            run.error = str(error)

    def _build_summary(self, pipeline: PipelineDefinition) -> PipelineSummaryResponse:
        nodes: list[PipelineNodeResponse] = [
            PipelineNodeResponse(
                id=task.name,
                kind=task.type,
                label=task.name,
                enabled=task.enabled,
                on_failure=task.on_failure,
                details={
                    "depends_on": ", ".join(task.depends_on) or "none",
                    "on_failure": task.on_failure,
                },
                yaml=yaml.safe_dump(
                    task.model_dump(mode="json", exclude_none=True),
                    sort_keys=False,
                ),
            )
            for task in pipeline.tasks
        ]
        edges: list[PipelineEdgeResponse] = [
            PipelineEdgeResponse(from_id=dependency, to_id=task.name)
            for task in pipeline.tasks
            for dependency in task.depends_on
        ]
        latest_id: UUID | None = self._latest_runs.get(pipeline.name)
        latest_run: PipelineResult | None = (
            self._runs.get(latest_id) if latest_id is not None else None
        )
        graph: PipelineGraphResponse = PipelineGraphResponse(
            nodes=nodes,
            edges=edges,
        )
        return PipelineSummaryResponse(
            name=pipeline.name,
            enabled=pipeline.enabled,
            description=pipeline.description,
            task_count=len(pipeline.tasks),
            graph=graph,
            latest_run=latest_run,
        )
