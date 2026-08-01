"""Dependency-injector container for application-wide dependencies."""

from dependency_injector import containers, providers

from app.connectors import PostgresPool
from app.core.config import AppSettings
from app.domain.gateway_application import GatewayApplication
from app.llm import OpenAICompatibleLlmClient
from app.policies import PolicyLoader
from app.proxy_factory import ProxyFactory
from app.services.config_loader import ConfigLoader
from app.services.guard import GuardService
from app.services.session import SessionService


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
    postgres_pool: providers.Singleton[PostgresPool] = providers.Singleton(
        PostgresPool,
        settings=settings.provided.database,
    )
    session_service: providers.Singleton[SessionService] = providers.Singleton(
        SessionService,
        pool=postgres_pool,
        idle_ttl_seconds=settings.provided.session.idle_ttl_seconds,
    )
    proxy_factory: providers.Singleton[ProxyFactory] = providers.Singleton(
        ProxyFactory,
        guard_service=guard_service,
        guard_settings=settings.provided.guard,
        session_store=session_service,
    )

    gateway_application: providers.Factory[GatewayApplication] = providers.Factory(
        GatewayApplication,
        settings=settings,
        loader=config_loader,
        policy_loader=policy_loader,
        proxy_factory=proxy_factory,
        postgres_pool=postgres_pool,
        session_store=session_service,
    )
