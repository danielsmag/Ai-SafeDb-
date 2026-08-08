"""Concurrent dependency-aware execution of declarative pipeline DAGs."""

import asyncio
from datetime import UTC, datetime
from uuid import uuid4

from app.services.pipelines.context import ExecutionContext
from app.services.pipelines.handlers import TaskHandler
from app.services.pipelines.models import (
    PipelineDefinition,
    PipelineResult,
    TaskDefinition,
    TaskResult,
)
from app.services.pipelines.registry import HandlerRegistry


class PipelineExecutor:
    """Execute ready DAG tasks concurrently while honoring failure policies."""

    def __init__(
        self,
        registry: HandlerRegistry,
        max_parallel_tasks: int = 4,
        task_timeout_seconds: float = 300.0,
        retry_count: int = 0,
    ) -> None:
        self._registry: HandlerRegistry = registry
        self._max_parallel_tasks: int = max_parallel_tasks
        self._task_timeout_seconds: float = task_timeout_seconds
        self._retry_count: int = retry_count

    async def execute(
        self,
        pipeline: PipelineDefinition,
        initial_context: ExecutionContext,
        result: PipelineResult | None = None,
    ) -> PipelineResult:
        """Execute a pipeline and return its complete run snapshot."""
        execution: PipelineResult = result or PipelineResult(
            run_id=uuid4(),
            pipeline_name=pipeline.name,
        )
        execution.status = "running"
        execution.started_at = datetime.now(UTC)
        execution.tasks = {
            task.name: TaskResult(name=task.name, type=task.type)
            for task in pipeline.tasks
        }
        context: ExecutionContext = initial_context.model_copy(deep=False)
        context.task_results = execution.tasks
        pending: dict[str, TaskDefinition] = {
            task.name: task for task in pipeline.tasks
        }
        semaphore: asyncio.Semaphore = asyncio.Semaphore(self._max_parallel_tasks)

        try:
            while pending:
                ready: list[TaskDefinition] = [
                    task
                    for task in pending.values()
                    if all(dependency not in pending for dependency in task.depends_on)
                ]
                if not ready:
                    execution.status = "failed"
                    execution.error = "pipeline execution stalled"
                    break

                async with asyncio.TaskGroup() as group:
                    scheduled: list[asyncio.Task[None]] = [
                        group.create_task(self._execute_task(task, context, semaphore))
                        for task in ready
                    ]
                for scheduled_task in scheduled:
                    scheduled_task.result()
                for task in ready:
                    del pending[task.name]

                failed: list[TaskResult] = [
                    execution.tasks[task.name]
                    for task in ready
                    if execution.tasks[task.name].status == "failed"
                ]
                if failed:
                    failure: TaskResult = failed[0]
                    execution.status = "failed"
                    execution.error = failure.error
                    self._skip_pending(pending, execution, "pipeline failed")
                    pending.clear()
        except asyncio.CancelledError:
            execution.status = "cancelled"
            execution.error = "pipeline run cancelled"
            self._cancel_unfinished(execution)
        finally:
            execution.finished_at = datetime.now(UTC)

        if execution.status == "running":
            execution.status = "succeeded"
        return execution

    async def _execute_task(
        self,
        task: TaskDefinition,
        context: ExecutionContext,
        semaphore: asyncio.Semaphore,
    ) -> None:
        current: TaskResult = context.task_results[task.name]
        if not task.enabled:
            current.status = "skipped"
            current.error = "task disabled"
            current.finished_at = datetime.now(UTC)
            return

        failed_dependencies: list[str] = [
            dependency
            for dependency in task.depends_on
            if context.task_results[dependency].status in {"failed", "cancelled"}
        ]
        if failed_dependencies:
            current.status = "skipped"
            current.error = "dependency failed: " + ", ".join(
                sorted(failed_dependencies)
            )
            current.finished_at = datetime.now(UTC)
            return

        dependencies: dict[str, TaskResult] = {
            dependency: context.task_results[dependency]
            for dependency in task.depends_on
        }
        current.status = "running"
        current.started_at = datetime.now(UTC)
        async with semaphore:
            handled: TaskResult = await self._execute_with_retries(
                task, dependencies, context
            )
        handled.started_at = current.started_at
        handled.finished_at = datetime.now(UTC)
        self._apply_failure_mode(task, handled)
        context.task_results[task.name] = handled

    async def _execute_with_retries(
        self,
        task: TaskDefinition,
        dependencies: dict[str, TaskResult],
        context: ExecutionContext,
    ) -> TaskResult:
        handler: TaskHandler = self._registry.get(task.type)
        last_error: str = "task failed"
        for attempt in range(self._retry_count + 1):
            try:
                result: TaskResult = await asyncio.wait_for(
                    handler.execute(task, dependencies, context),
                    timeout=self._task_timeout_seconds,
                )
                result.metadata["attempt"] = attempt + 1
                return result
            except TimeoutError:
                last_error = (
                    f"task timed out after {self._task_timeout_seconds:g} seconds"
                )
            except Exception as error:
                last_error = str(error) or type(error).__name__
        return TaskResult(
            name=task.name,
            type=task.type,
            status="failed",
            error=last_error,
            metadata={"attempt": self._retry_count + 1},
        )

    @staticmethod
    def _apply_failure_mode(task: TaskDefinition, result: TaskResult) -> None:
        if result.status != "failed" or task.on_failure == "fail":
            return
        error: str = result.error or "task failed"
        if task.on_failure == "skip":
            result.status = "skipped"
        else:
            result.status = "succeeded"
            result.metadata["warning"] = error

    @staticmethod
    def _skip_pending(
        pending: dict[str, TaskDefinition],
        execution: PipelineResult,
        reason: str,
    ) -> None:
        finished_at: datetime = datetime.now(UTC)
        for task in pending.values():
            result: TaskResult = execution.tasks[task.name]
            result.status = "skipped"
            result.error = reason
            result.finished_at = finished_at

    @staticmethod
    def _cancel_unfinished(execution: PipelineResult) -> None:
        finished_at: datetime = datetime.now(UTC)
        for result in execution.tasks.values():
            if result.status in {"pending", "running"}:
                result.status = "cancelled"
                result.error = "pipeline run cancelled"
                result.finished_at = finished_at
