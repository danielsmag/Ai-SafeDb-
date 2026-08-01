from pathlib import Path

import pytest
from fastapi import FastAPI

from app.core.bootstrap import ApplicationBootstrap
from app.core.config import AppSettings
from app.core.container import ApplicationContainer


def test_settings_are_loaded_and_normalized_from_environment(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("GATEWAY_MOUNT_PREFIX", "gateway/mcp/")
    monkeypatch.setenv("GATEWAY_PUBLIC_BASE_URL", "https://gateway.example.com/")

    settings: AppSettings = AppSettings()

    assert settings.mount_prefix == "/gateway/mcp"
    assert settings.public_base_url == "https://gateway.example.com"


def test_container_applies_expected_dependency_lifetimes(tmp_path: Path) -> None:
    settings: AppSettings = AppSettings(config_dir=tmp_path)
    container: ApplicationContainer = ApplicationContainer(settings=settings)

    assert container.settings() is settings
    assert container.config_loader() is not container.config_loader()
    assert container.proxy_factory() is container.proxy_factory()
    assert container.postgres_pool() is container.postgres_pool()
    assert container.session_service() is container.session_service()
    assert (
        container.postgres_pool().schema_name == settings.database.schema_name
    )

def test_bootstrap_exposes_container_on_application_state(tmp_path: Path) -> None:
    settings: AppSettings = AppSettings(config_dir=tmp_path)

    api: FastAPI = ApplicationBootstrap(settings).run()

    container: ApplicationContainer = api.state.container
    assert container.settings() is settings
    route_paths: set[str | None] = {
        getattr(route, "path", None) for route in api.routes
    }
    assert route_paths >= {
        "/health",
        "/servers",
        "/sessions/data-key",
        "/sessions/{mcp_session_id}/data-key",
    }
