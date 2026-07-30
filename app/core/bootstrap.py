"""Application bootstrap sequence and composition root."""

from fastapi.applications import FastAPI

from app.core.config import AppSettings
from app.core.container import ApplicationContainer
from app.core.logging import configure_logging


class ApplicationBootstrap:
    """Initialize configuration, logging, dependencies, and the API."""

    def __init__(self, settings: AppSettings | None = None) -> None:
        self._settings: AppSettings = (
            settings if settings is not None else AppSettings()
        )

    def run(self) -> FastAPI:
        """Run startup assembly in dependency order."""
        self._configure_logging()
        container: ApplicationContainer = ApplicationContainer(settings=self._settings)
        api: FastAPI = container.gateway_application().build()
        api.state.container = container
        return api

    def _configure_logging(self) -> None:
        configure_logging(self._settings.log_level)


def bootstrap_application(settings: AppSettings | None = None) -> FastAPI:
    """Create the application through the standard bootstrap sequence."""
    return ApplicationBootstrap(settings).run()
