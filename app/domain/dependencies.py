"""Authentication and authorization dependencies for gateway HTTP handlers."""

from fastapi import HTTPException, Request

from app.connectors.models import ApiKey, User
from app.core.config import AppSettings
from app.services.auth import AuthStore
from app.services.session import SessionStore


async def require_user_session(
    settings: AppSettings,
    auth_store: AuthStore | None,
    request: Request,
) -> User:
    if auth_store is None:
        raise HTTPException(
            status_code=503,
            detail="web authentication unavailable",
        )
    raw_token: str | None = request.cookies.get(settings.auth.cookie_name)
    if raw_token is None:
        raise HTTPException(status_code=401, detail="not authenticated")
    user: User | None = await auth_store.resolve_session(raw_token)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail="session is invalid or expired",
        )
    return user


async def require_admin_session(
    settings: AppSettings,
    auth_store: AuthStore | None,
    request: Request,
) -> User:
    user: User = await require_user_session(settings, auth_store, request)
    if not user.is_admin:
        raise HTTPException(
            status_code=403,
            detail="administrator access required",
        )
    return user


async def require_bearer_api_key(
    store: SessionStore,
    authorization: str | None,
) -> ApiKey:
    if authorization is None:
        raise HTTPException(
            status_code=401,
            detail="missing Authorization header",
        )
    parts: list[str] = authorization.split(" ", maxsplit=1)
    if len(parts) != 2 or parts[0].lower() != "bearer" or not parts[1].strip():
        raise HTTPException(
            status_code=401,
            detail="Authorization header must be Bearer <api_key>",
        )
    raw_key: str = parts[1].strip()
    api_key: ApiKey | None = await store.authenticate(raw_key)
    if api_key is None:
        raise HTTPException(
            status_code=401,
            detail="invalid or revoked API key",
        )
    return api_key
