from pathlib import Path

import pytest
from fastapi import FastAPI

from app.core.bootstrap import ApplicationBootstrap
from app.core.config import AppSettings
from app.core.container import ApplicationContainer
from app.domain.gateway_application import GatewayApplication
from app.proxy_factory import ProxyFactory
from app.services.config_loader import ConfigLoader
from app.services.pipelines import HandlerRegistry, PipelineExecutor, PipelineLoader
from app.services.pipelines.handlers import OutputHandler


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


def test_settings_load_from_toml_and_env_overrides(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("GATEWAY_LOG_LEVEL", raising=False)
    monkeypatch.delenv("GATEWAY_LLM__GUARD_MODEL", raising=False)
    monkeypatch.delenv("GATEWAY_GUARD__ENABLED", raising=False)
    (tmp_path / "settings.toml").write_text(
        "\n".join(
            [
                'log_level = "DEBUG"',
                "[llm]",
                'guard_model = "from-toml"',
                "[guard]",
                "enabled = true",
                "",
            ]
        ),
        encoding="utf-8",
    )

    from_toml: AppSettings = AppSettings()
    assert from_toml.log_level == "DEBUG"
    assert from_toml.llm.guard_model == "from-toml"
    assert from_toml.guard.enabled is True

    monkeypatch.setenv("GATEWAY_LLM__GUARD_MODEL", "from-env")
    from_env: AppSettings = AppSettings()
    assert from_env.llm.guard_model == "from-env"
    assert from_env.guard.enabled is True


def test_container_applies_expected_dependency_lifetimes(tmp_path: Path) -> None:
    settings: AppSettings = AppSettings(config_dir=tmp_path)
    container: ApplicationContainer = ApplicationContainer(settings=settings)

    assert container.settings() is settings
    assert container.config_loader() is not container.config_loader()
    assert container.pipeline_loader() is not container.pipeline_loader()
    assert container.pipeline_executor() is not container.pipeline_executor()
    assert container.handler_registry() is container.handler_registry()
    assert container.proxy_factory() is container.proxy_factory()
    assert container.database() is container.database()
    assert container.session_service() is container.session_service()
    assert (
        container.database().schema_name == settings.database.schema_name
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
        "/api/v1/health",
        "/api/v1/servers",
        "/api/v1/manager/pipelines",
        "/api/v1/manager/pipelines/{pipeline_name}/runs",
        "/api/v1/manager/pipeline-runs/{run_id}",
        "/api/v1/manager/pipeline-runs/{run_id}/cancel",
        "/api/v1/sessions/data-key",
        "/api/v1/sessions/{mcp_session_id}/data-key",
    }


def test_pipeline_routes_do_not_require_history_store(tmp_path: Path) -> None:
    config_dir: Path = tmp_path / "mcp-servers"
    pipelines_dir: Path = tmp_path / "pipelines"
    config_dir.mkdir()
    pipelines_dir.mkdir()
    (pipelines_dir / "demo.yaml").write_text(
        "name: demo\ntasks:\n  - name: publish\n    type: output\n",
        encoding="utf-8",
    )
    settings: AppSettings = AppSettings(
        config_dir=config_dir,
        pipelines_dir=pipelines_dir,
    )
    registry: HandlerRegistry = HandlerRegistry([OutputHandler()])
    gateway: GatewayApplication = GatewayApplication(
        settings=settings,
        loader=ConfigLoader(config_dir),
        proxy_factory=ProxyFactory(),
        pipeline_loader=PipelineLoader(pipelines_dir),
        pipeline_executor=PipelineExecutor(registry),
    )

    api: FastAPI = gateway.build()
    route_paths: set[str | None] = {
        getattr(route, "path", None) for route in api.routes
    }

    assert "/api/v1/manager/pipelines" in route_paths
    assert "/api/v1/manager/pipelines/{pipeline_name}/runs" in route_paths
