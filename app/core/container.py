"""Dependency-injector container for application-wide dependencies."""

from dependency_injector import containers, providers

from app.core.config import AppSettings
from app.core.database import Database
from app.domain.gateway_application import GatewayApplication
from app.llm import OpenAICompatibleLlmClient
from app.policies import PolicyLoader
from app.proxy_factory import ProxyFactory
from app.services.auth import AuthService
from app.services.config_loader import ConfigLoader
from app.services.guard import GuardService
from app.services.history import PostgresHistoryStore
from app.services.pipelines import HandlerRegistry, PipelineExecutor, PipelineLoader
from app.services.pipelines.handlers import (
    CustomHandler,
    GuardHandler,
    McpServerHandler,
    OutputHandler,
    PolicyHandler,
    SourceHandler,
    TransformHandler,
    ValidationHandler,
)
from app.services.rewriter import PiiQueryRewriter
from app.services.session import SessionService
from app.services.workflows import WorkflowLoader


class ApplicationContainer(containers.DeclarativeContainer):
    """Declare dependency lifetimes and application object construction."""

    settings: providers.Dependency[AppSettings] = providers.Dependency(
        instance_of=AppSettings
    )

    config_loader: providers.Factory[ConfigLoader] = providers.Factory(
        ConfigLoader,
        config_dir=settings.provided.config_dir,
    )
    policy_loader: providers.Factory[PolicyLoader] = providers.Factory(
        PolicyLoader,
        policies_dir=settings.provided.policies_dir,
    )
    workflow_loader: providers.Factory[WorkflowLoader] = providers.Factory(
        WorkflowLoader,
        workflows_dir=settings.provided.workflows_dir,
        sources_dir=settings.provided.sources_dir,
        outputs_dir=settings.provided.outputs_dir,
    )
    pipeline_loader: providers.Factory[PipelineLoader] = providers.Factory(
        PipelineLoader,
        pipelines_dir=settings.provided.pipelines_dir,
    )
    handler_registry: providers.Singleton[HandlerRegistry] = providers.Singleton(
        HandlerRegistry,
        handlers=providers.List(
            providers.Singleton(SourceHandler),
            providers.Singleton(PolicyHandler),
            providers.Singleton(TransformHandler),
            providers.Singleton(ValidationHandler),
            providers.Singleton(GuardHandler),
            providers.Singleton(McpServerHandler),
            providers.Singleton(OutputHandler),
            providers.Singleton(CustomHandler),
        ),
    )
    pipeline_executor: providers.Factory[PipelineExecutor] = providers.Factory(
        PipelineExecutor,
        registry=handler_registry,
        max_parallel_tasks=settings.provided.pipeline.max_parallel_tasks,
        task_timeout_seconds=settings.provided.pipeline.task_timeout_seconds,
        retry_count=settings.provided.pipeline.retry_count,
    )
    llm_client: providers.Singleton[OpenAICompatibleLlmClient] = providers.Singleton(
        OpenAICompatibleLlmClient,
        base_url=settings.provided.llm.base_url,
        api_key=settings.provided.llm.api_key,
        timeout_seconds=settings.provided.llm.timeout_seconds,
        max_concurrency=settings.provided.llm.max_concurrency,
        keep_alive=settings.provided.llm.keep_alive,
    )
    guard_service: providers.Singleton[GuardService] = providers.Singleton(
        GuardService,
        client=llm_client,
        model=settings.provided.llm.guard_model,
        on_error=settings.provided.guard.on_error,
        cache_ttl_seconds=settings.provided.guard.cache_ttl_seconds,
    )
    pii_query_rewriter: providers.Singleton[PiiQueryRewriter] = providers.Singleton(
        PiiQueryRewriter,
        client=llm_client,
        model=settings.provided.llm.rewrite_model,
        on_error=settings.provided.guard.on_error,
    )
    database: providers.Singleton[Database] = providers.Singleton(
        Database,
        settings=settings.provided.database,
    )
    session_service: providers.Singleton[SessionService] = providers.Singleton(
        SessionService,
        database=database,
        idle_ttl_seconds=settings.provided.session.idle_ttl_seconds,
    )
    auth_service: providers.Singleton[AuthService] = providers.Singleton(
        AuthService,
        database=database,
        session_ttl_seconds=settings.provided.auth.session_ttl_seconds,
    )
    history_store: providers.Singleton[PostgresHistoryStore] = providers.Singleton(
        PostgresHistoryStore,
        database=database,
    )
    proxy_factory: providers.Singleton[ProxyFactory] = providers.Singleton(
        ProxyFactory,
        guard_service=guard_service,
        guard_settings=settings.provided.guard,
        session_store=session_service,
        pii_query_rewriter=pii_query_rewriter,
        history_store=history_store,
    )

    gateway_application: providers.Factory[GatewayApplication] = providers.Factory(
        GatewayApplication,
        settings=settings,
        loader=config_loader,
        policy_loader=policy_loader,
        proxy_factory=proxy_factory,
        database=database,
        session_store=session_service,
        auth_store=auth_service,
        history_store=history_store,
        workflow_loader=workflow_loader,
        pipeline_loader=pipeline_loader,
        pipeline_executor=pipeline_executor,
        guard_service=guard_service,
    )
