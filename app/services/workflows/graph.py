"""Build renderable DAGs out of workflow definitions."""

from typing import Any

import yaml
from pydantic import BaseModel

from app.models import McpServerConfig
from app.policies import Policy
from app.schemas import (
    WorkflowEdgeResponse,
    WorkflowGraphResponse,
    WorkflowNodeResponse,
    WorkflowSummaryResponse,
)
from app.services.workflows.models import (
    OutputEndpointDefinition,
    SourceServerDefinition,
    WorkflowCatalog,
    WorkflowDefinition,
)


def _dump_yaml(model: BaseModel) -> str:
    """Render a validated definition back to YAML for display in the UI."""
    data: dict[str, Any] = model.model_dump(mode="json", exclude_none=True)
    return yaml.safe_dump(data, sort_keys=False, default_flow_style=False)


def build_workflow_summary(
    workflow: WorkflowDefinition,
    catalog: WorkflowCatalog,
    mcp_servers: dict[str, McpServerConfig],
    policies: dict[str, Policy],
) -> WorkflowSummaryResponse:
    """Resolve one workflow's references into a summary with a DAG."""
    nodes: list[WorkflowNodeResponse] = []
    edges: list[WorkflowEdgeResponse] = []

    source_node: WorkflowNodeResponse = _source_node(
        workflow.source, catalog.sources.get(workflow.source)
    )
    mcp_node: WorkflowNodeResponse = _mcp_node(
        workflow.mcp_server, mcp_servers.get(workflow.mcp_server)
    )
    output_node: WorkflowNodeResponse = _output_node(
        workflow.output, catalog.outputs.get(workflow.output)
    )
    policy_nodes: list[WorkflowNodeResponse] = [
        _policy_node(name, policies.get(name)) for name in workflow.policies
    ]

    nodes.append(source_node)
    nodes.append(mcp_node)
    nodes.extend(policy_nodes)
    nodes.append(output_node)

    edges.append(WorkflowEdgeResponse(from_id=source_node.id, to_id=mcp_node.id))
    if policy_nodes:
        for policy_node in policy_nodes:
            edges.append(
                WorkflowEdgeResponse(from_id=mcp_node.id, to_id=policy_node.id)
            )
            edges.append(
                WorkflowEdgeResponse(from_id=policy_node.id, to_id=output_node.id)
            )
    else:
        edges.append(WorkflowEdgeResponse(from_id=mcp_node.id, to_id=output_node.id))

    valid: bool = not any(node.missing for node in nodes)
    return WorkflowSummaryResponse(
        name=workflow.name,
        enabled=workflow.enabled,
        description=workflow.description,
        source=workflow.source,
        mcp_server=workflow.mcp_server,
        policies=list(workflow.policies),
        output=workflow.output,
        valid=valid,
        graph=WorkflowGraphResponse(nodes=nodes, edges=edges),
    )


def _source_node(
    name: str,
    definition: SourceServerDefinition | None,
) -> WorkflowNodeResponse:
    details: dict[str, str] = {}
    sublabel: str | None = None
    if definition is not None:
        sublabel = definition.kind
        details["kind"] = definition.kind
        if definition.host is not None:
            port: str = f":{definition.port}" if definition.port is not None else ""
            details["host"] = f"{definition.host}{port}"
        if definition.database is not None:
            details["database"] = definition.database
        if definition.description is not None:
            details["description"] = definition.description
    return WorkflowNodeResponse(
        id=f"source:{name}",
        kind="source",
        label=name,
        sublabel=sublabel,
        missing=definition is None,
        details=details,
        yaml=_dump_yaml(definition) if definition is not None else None,
    )


def _mcp_node(
    name: str,
    config: McpServerConfig | None,
) -> WorkflowNodeResponse:
    details: dict[str, str] = {}
    sublabel: str | None = None
    if config is not None:
        sublabel = config.source.transport
        details["transport"] = config.source.transport
        if config.description is not None:
            details["description"] = config.description
        if config.policy is not None:
            details["policy"] = config.policy
    return WorkflowNodeResponse(
        id=f"mcp:{name}",
        kind="mcp",
        label=name,
        sublabel=sublabel,
        missing=config is None,
        details=details,
        yaml=_dump_yaml(config) if config is not None else None,
    )


def _policy_node(
    name: str,
    policy: Policy | None,
) -> WorkflowNodeResponse:
    details: dict[str, str] = {}
    sublabel: str | None = None
    if policy is not None:
        sublabel = f"{policy.type} · {policy.dialect}"
        details["type"] = policy.type
        details["dialect"] = policy.dialect
        details["read_only"] = "yes" if policy.read_only else "no"
        details["tables"] = str(len(policy.access.tables))
        pii_count: int = sum(len(table.pii) for table in policy.access.tables)
        details["pii_rules"] = str(pii_count)
    return WorkflowNodeResponse(
        id=f"policy:{name}",
        kind="policy",
        label=name,
        sublabel=sublabel,
        missing=policy is None,
        details=details,
        yaml=_dump_yaml(policy) if policy is not None else None,
    )


def _output_node(
    name: str,
    definition: OutputEndpointDefinition | None,
) -> WorkflowNodeResponse:
    details: dict[str, str] = {}
    sublabel: str | None = None
    if definition is not None:
        sublabel = definition.transport
        details["transport"] = definition.transport
        if definition.url is not None:
            details["url"] = definition.url
        if definition.description is not None:
            details["description"] = definition.description
    return WorkflowNodeResponse(
        id=f"output:{name}",
        kind="output",
        label=name,
        sublabel=sublabel,
        missing=definition is None,
        details=details,
        yaml=_dump_yaml(definition) if definition is not None else None,
    )
