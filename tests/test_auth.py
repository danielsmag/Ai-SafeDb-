"""Tests for web-console username/password authentication."""

from pathlib import Path

import httpx
from fastapi import FastAPI

from app.domain.gateway_application import GatewayApplication
from app.proxy_factory import ProxyFactory
from app.services.auth import (
    DEV_PASSWORD,
    DEV_USERNAME,
    MemoryAuthService,
)
from app.services.config_loader import ConfigLoader
from app.services.session import MemorySessionService
from app.settings import AppSettings


def build_auth_app(tmp_path: Path, auth: MemoryAuthService) -> FastAPI:
    sessions: MemorySessionService = MemorySessionService()
    settings: AppSettings = AppSettings(
        config_dir=tmp_path,
        public_base_url="http://gateway.test",
    )
    gateway: GatewayApplication = GatewayApplication(
        settings=settings,
        loader=ConfigLoader(tmp_path),
        proxy_factory=ProxyFactory(session_store=sessions),
        session_store=sessions,
        auth_store=auth,
    )
    return gateway.build()


async def test_login_identity_logout_cookie_flow(tmp_path: Path) -> None:
    auth: MemoryAuthService = MemoryAuthService()
    app: FastAPI = build_auth_app(tmp_path, auth)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        anonymous: httpx.Response = await client.get("/api/v1/client/me")
        invalid: httpx.Response = await client.post(
            "/api/v1/client/login",
            json={"username": DEV_USERNAME, "password": "wrong"},
        )
        logged_in: httpx.Response = await client.post(
            "/api/v1/client/login",
            json={"username": DEV_USERNAME, "password": DEV_PASSWORD},
        )
        identity: httpx.Response = await client.get("/api/v1/client/me")
        logout: httpx.Response = await client.post("/api/v1/client/logout")
        after_logout: httpx.Response = await client.get("/api/v1/client/me")

    assert anonymous.status_code == 401
    assert invalid.status_code == 401
    assert logged_in.status_code == 200
    assert "HttpOnly" in logged_in.headers["set-cookie"]
    assert identity.json()["username"] == DEV_USERNAME
    assert logout.status_code == 204
    assert after_logout.status_code == 401


async def test_expired_session_is_rejected(tmp_path: Path) -> None:
    auth: MemoryAuthService = MemoryAuthService()
    app: FastAPI = build_auth_app(tmp_path, auth)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    ) as client:
        logged_in: httpx.Response = await client.post(
            "/api/v1/client/login",
            json={"username": DEV_USERNAME, "password": DEV_PASSWORD},
        )
        raw_token: str = client.cookies["aisafedb_session"]
        auth.expire_session(raw_token)
        expired: httpx.Response = await client.get("/api/v1/client/me")

    assert logged_in.status_code == 200
    assert expired.status_code == 401
