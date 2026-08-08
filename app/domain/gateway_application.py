"""Backward-compatible re-export; prefer ``app.domain.gateway``."""

from app.domain.application import GatewayApplication

__all__: list[str] = ["GatewayApplication"]
