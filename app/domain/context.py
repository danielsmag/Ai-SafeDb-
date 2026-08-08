"""Runtime context shared across gateway route modules during application build."""

from dataclasses import dataclass

from app.core.config import AppSettings
from app.models import McpServerConfig
from app.policies import Policy
from app.schemas import ServerSummary
from app.services.auth import AuthStore
from app.services.history import HistoryStore
from app.services.pipelines import PipelineService
from app.services.session import SessionStore
from app.services.workflows import WorkflowCatalog


@dataclass(frozen=True)
class GatewayContext:
    """Dependencies and loaded catalog state for HTTP route handlers."""

    settings: AppSettings
    session_store: SessionStore | None
    auth_store: AuthStore | None
    history_store: HistoryStore | None
    pipeline_service: PipelineService | None
    policies: dict[str, Policy]
    workflow_catalog: WorkflowCatalog
    configs: list[McpServerConfig]
    server_summaries: list[ServerSummary]
