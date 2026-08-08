"""Client UI authentication routes."""

from fastapi import FastAPI, HTTPException, Request, Response

from app.connectors.models import User, WebSession
from app.domain.context import GatewayContext
from app.domain.dependencies import require_user_session
from app.domain.paths import CLIENT_API_PREFIX
from app.schemas import LoginRequest, UserIdentityResponse
from app.services.auth import AuthStore


def register_client_auth_routes(api: FastAPI, ctx: GatewayContext) -> None:
    store: AuthStore | None = ctx.auth_store
    if store is None:
        return

    @api.post(
        f"{CLIENT_API_PREFIX}/login",
        response_model=UserIdentityResponse,
        tags=["client-ui"],
    )
    async def login(
        credentials: LoginRequest,
        response: Response,
    ) -> UserIdentityResponse:
        user: User | None = await store.authenticate(
            credentials.username, credentials.password
        )
        if user is None:
            raise HTTPException(
                status_code=401,
                detail="invalid username or password",
            )
        created_session: tuple[WebSession, str] = await store.create_session(user)
        raw_token: str = created_session[1]
        response.set_cookie(
            key=ctx.settings.auth.cookie_name,
            value=raw_token,
            max_age=int(ctx.settings.auth.session_ttl_seconds),
            httponly=True,
            secure=ctx.settings.auth.cookie_secure,
            samesite="lax",
            path="/",
        )
        return UserIdentityResponse(
            username=user.username,
            is_admin=user.is_admin,
            created_at=user.created_at,
        )

    @api.post(f"{CLIENT_API_PREFIX}/logout", status_code=204, tags=["client-ui"])
    async def logout(request: Request, response: Response) -> None:
        raw_token: str | None = request.cookies.get(ctx.settings.auth.cookie_name)
        if raw_token is not None:
            await store.revoke_session(raw_token)
        response.delete_cookie(
            key=ctx.settings.auth.cookie_name,
            path="/",
            secure=ctx.settings.auth.cookie_secure,
            httponly=True,
            samesite="lax",
        )

    @api.get(
        f"{CLIENT_API_PREFIX}/me",
        response_model=UserIdentityResponse,
        tags=["client-ui"],
    )
    async def get_identity(request: Request) -> UserIdentityResponse:
        user: User = await require_user_session(
            ctx.settings, ctx.auth_store, request
        )
        return UserIdentityResponse(
            username=user.username,
            is_admin=user.is_admin,
            created_at=user.created_at,
        )
