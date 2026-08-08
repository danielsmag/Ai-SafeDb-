"""MCP server proxy assembly for gateway mounts."""

from fastmcp import FastMCP
from fastmcp.server.http import StarletteWithLifespan

from app.core.config import AppSettings
from app.exceptions import GatewayError
from app.models import McpServerConfig
from app.policies import Policy
from app.proxy_factory import ProxyFactory


def public_url(settings: AppSettings, config: McpServerConfig) -> str:
    return (
        f"{settings.public_base_url}"
        f"{config.mount_path(settings.mount_prefix)}"
    )


def build_mcp_app(
    settings: AppSettings,
    proxy_factory: ProxyFactory,
    config: McpServerConfig,
    policies: dict[str, Policy],
) -> StarletteWithLifespan:
    policy: Policy | None = (
        policies.get(config.policy) if config.policy is not None else None
    )
    if config.policy is not None and policy is None:
        raise GatewayError(
            f"server {config.name!r} references unknown policy {config.policy!r}"
        )
    proxy: FastMCP = proxy_factory.create(config, policy)
    return proxy.http_app(
        path="/",
        stateless_http=settings.stateless_http,
        json_response=settings.json_response,
        allowed_hosts=settings.allowed_hosts or None,
        allowed_origins=settings.allowed_origins or None,
    )
