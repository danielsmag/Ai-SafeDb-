"""Tests for the workflow catalog loader and DAG builder."""

from pathlib import Path

import pytest

from app.exceptions import ConfigError
from app.models import McpServerConfig
from app.policies.models import SqlPolicy
from app.schemas import WorkflowSummaryResponse
from app.services.workflows import (
    WorkflowCatalog,
    WorkflowLoader,
    build_workflow_summary,
)


def _write(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")


@pytest.fixture()
def catalog_dirs(tmp_path: Path) -> tuple[Path, Path, Path]:
    workflows_dir: Path = tmp_path / "workflows"
    sources_dir: Path = tmp_path / "sources"
    outputs_dir: Path = tmp_path / "outputs"
    workflows_dir.mkdir()
    sources_dir.mkdir()
    outputs_dir.mkdir()

    _write(
        sources_dir / "db.yaml",
        "name: db\nkind: postgres\nhost: localhost\nport: 5432\ndatabase: appdb\n",
    )
    _write(
        outputs_dir / "endpoint.yaml",
        "name: endpoint\ntransport: http\nurl: http://localhost:8000/mcp/db\n",
    )
    _write(
        workflows_dir / "flow.yaml",
        (
            "name: flow\n"
            "source: db\n"
            "mcp_server: db-mcp\n"
            "policies:\n"
            "  - readonly\n"
            "output: endpoint\n"
        ),
    )
    return workflows_dir, sources_dir, outputs_dir


def test_loader_reads_all_sections(catalog_dirs: tuple[Path, Path, Path]) -> None:
    workflows_dir, sources_dir, outputs_dir = catalog_dirs
    loader: WorkflowLoader = WorkflowLoader(workflows_dir, sources_dir, outputs_dir)
    catalog: WorkflowCatalog = loader.load()

    assert set(catalog.sources) == {"db"}
    assert set(catalog.outputs) == {"endpoint"}
    assert set(catalog.workflows) == {"flow"}
    assert catalog.workflows["flow"].policies == ["readonly"]


def test_loader_tolerates_missing_directories(tmp_path: Path) -> None:
    loader: WorkflowLoader = WorkflowLoader(
        tmp_path / "missing-workflows",
        tmp_path / "missing-sources",
        tmp_path / "missing-outputs",
    )
    catalog: WorkflowCatalog = loader.load()

    assert catalog.sources == {}
    assert catalog.outputs == {}
    assert catalog.workflows == {}


def test_loader_skips_disabled_definitions(
    catalog_dirs: tuple[Path, Path, Path],
) -> None:
    workflows_dir, sources_dir, outputs_dir = catalog_dirs
    _write(workflows_dir / "off.yaml", "name: off\nenabled: false\n")
    loader: WorkflowLoader = WorkflowLoader(workflows_dir, sources_dir, outputs_dir)
    catalog: WorkflowCatalog = loader.load()

    assert "off" not in catalog.workflows


def test_loader_rejects_duplicate_names(
    catalog_dirs: tuple[Path, Path, Path],
) -> None:
    workflows_dir, sources_dir, outputs_dir = catalog_dirs
    _write(sources_dir / "other.yaml", "name: db\nkind: postgres\n")
    loader: WorkflowLoader = WorkflowLoader(workflows_dir, sources_dir, outputs_dir)

    with pytest.raises(ConfigError):
        loader.load()


def test_graph_resolves_full_chain(catalog_dirs: tuple[Path, Path, Path]) -> None:
    workflows_dir, sources_dir, outputs_dir = catalog_dirs
    loader: WorkflowLoader = WorkflowLoader(workflows_dir, sources_dir, outputs_dir)
    catalog: WorkflowCatalog = loader.load()

    mcp_config: McpServerConfig = McpServerConfig.model_validate(
        {
            "name": "db-mcp",
            "source": {"transport": "stdio", "command": "npx"},
            "policy": "readonly",
        }
    )
    policy: SqlPolicy = SqlPolicy.model_validate(
        {"name": "readonly", "type": "sql", "dialect": "postgres", "read_only": True}
    )

    summary: WorkflowSummaryResponse = build_workflow_summary(
        catalog.workflows["flow"],
        catalog,
        {"db-mcp": mcp_config},
        {"readonly": policy},
    )

    assert summary.valid is True
    node_ids: list[str] = [node.id for node in summary.graph.nodes]
    assert node_ids == ["source:db", "mcp:db-mcp", "policy:readonly", "output:endpoint"]
    edge_pairs: list[tuple[str, str]] = [
        (edge.from_id, edge.to_id) for edge in summary.graph.edges
    ]
    assert edge_pairs == [
        ("source:db", "mcp:db-mcp"),
        ("mcp:db-mcp", "policy:readonly"),
        ("policy:readonly", "output:endpoint"),
    ]


def test_graph_flags_unresolved_references(
    catalog_dirs: tuple[Path, Path, Path],
) -> None:
    workflows_dir, sources_dir, outputs_dir = catalog_dirs
    loader: WorkflowLoader = WorkflowLoader(workflows_dir, sources_dir, outputs_dir)
    catalog: WorkflowCatalog = loader.load()

    summary: WorkflowSummaryResponse = build_workflow_summary(
        catalog.workflows["flow"], catalog, {}, {}
    )

    assert summary.valid is False
    missing_by_id: dict[str, bool] = {
        node.id: node.missing for node in summary.graph.nodes
    }
    assert missing_by_id["source:db"] is False
    assert missing_by_id["output:endpoint"] is False
    assert missing_by_id["mcp:db-mcp"] is True
    assert missing_by_id["policy:readonly"] is True


def test_graph_without_policies_links_mcp_to_output(
    catalog_dirs: tuple[Path, Path, Path],
) -> None:
    workflows_dir, sources_dir, outputs_dir = catalog_dirs
    _write(
        workflows_dir / "direct.yaml",
        "name: direct\nsource: db\nmcp_server: db-mcp\noutput: endpoint\n",
    )
    loader: WorkflowLoader = WorkflowLoader(workflows_dir, sources_dir, outputs_dir)
    catalog: WorkflowCatalog = loader.load()

    summary: WorkflowSummaryResponse = build_workflow_summary(
        catalog.workflows["direct"], catalog, {}, {}
    )

    edge_pairs: list[tuple[str, str]] = [
        (edge.from_id, edge.to_id) for edge in summary.graph.edges
    ]
    assert ("mcp:db-mcp", "output:endpoint") in edge_pairs
