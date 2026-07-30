"""Dependency-injector container for application-wide dependencies."""

from dependency_injector import containers, providers

from app.core.config import AppSettings
from app.domain.gateway_application import GatewayApplication
from app.proxy_factory import ProxyFactory
from app.services.config_loader import ConfigLoader


class ApplicationContainer(containers.DeclarativeContainer):
    """Declare dependency lifetimes and application object construction."""

    settings: providers.Dependency[AppSettings] = providers.Dependency(
        instance_of=AppSettings
    )

    config_loader: providers.Factory[ConfigLoader] = providers.Factory(
        ConfigLoader,
        config_dir=settings.provided.config_dir,
    )
    proxy_factory: providers.Singleton[ProxyFactory] = providers.Singleton(ProxyFactory)

    gateway_application: providers.Factory[GatewayApplication] = providers.Factory(
        GatewayApplication,
        settings=settings,
        loader=config_loader,
        proxy_factory=proxy_factory,
    )
