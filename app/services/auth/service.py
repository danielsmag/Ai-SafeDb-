"""Username/password authentication and browser-session persistence."""

from datetime import UTC, datetime, timedelta
from typing import Protocol, cast
from uuid import UUID, uuid4

from sqlalchemy import delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.dialects.postgresql.dml import Insert
from sqlalchemy.engine import CursorResult, Result
from sqlalchemy.sql.dml import Update
from sqlalchemy.sql.selectable import Select
from sqlmodel import col, select

from app.connectors.models import User, WebSession
from app.connectors.orm_models import UserORM, WebSessionORM
from app.core.database import Database
from app.core.logging import logger
from app.services.auth.keys import (
    generate_session_token,
    hash_password,
    hash_session_token,
    verify_password,
)

DEV_USER_ID: UUID = UUID("00000000-0000-4000-8000-000000000010")
DEV_USERNAME: str = "admin"
DEV_PASSWORD: str = "changeme"
DEV_PASSWORD_HASH: str = (
    "$2b$12$Wd.dqXEa0zXJr0MJtuywieBLWwJAxSlN1d5m/YUQcOTPIK5vlI.HC"
)


class AuthStore(Protocol):
    """Persistence contract for web-console authentication."""

    async def ensure_schema(self) -> None: ...

    async def authenticate(self, username: str, password: str) -> User | None: ...

    async def create_session(self, user: User) -> tuple[WebSession, str]: ...

    async def resolve_session(self, raw_token: str) -> User | None: ...

    async def revoke_session(self, raw_token: str) -> bool: ...

    async def list_users(self) -> list[User]: ...

    async def get_user(self, user_id: UUID) -> User | None: ...

    async def create_user(
        self, username: str, password: str, is_admin: bool = False
    ) -> User: ...

    async def update_user(
        self,
        user_id: UUID,
        *,
        password: str | None = None,
        is_admin: bool | None = None,
        disabled: bool | None = None,
    ) -> User | None: ...


class AuthService:
    """Authenticate users and maintain server-side browser sessions."""

    def __init__(self, database: Database, session_ttl_seconds: float) -> None:
        self._database: Database = database
        self._session_ttl_seconds: float = session_ttl_seconds

    async def ensure_schema(self) -> None:
        """Create app tables and seed the local development user."""
        await self._database.create_all()
        async with self._database.session() as session:
            statement: Insert = (
                insert(UserORM)
                .values(
                    id=DEV_USER_ID,
                    username=DEV_USERNAME,
                    password_hash=DEV_PASSWORD_HASH,
                    is_admin=True,
                )
                .on_conflict_do_update(
                    index_elements=[UserORM.username],
                    set_={"is_admin": True},
                )
            )
            await session.execute(statement)
            await session.commit()
        logger.info("Ensured web authentication schema %r", self._database.schema_name)

    async def authenticate(self, username: str, password: str) -> User | None:
        """Return an enabled user when supplied credentials are valid."""
        async with self._database.session() as session:
            statement: Select[tuple[UserORM]] = select(UserORM).where(
                col(UserORM.username) == username,
                col(UserORM.disabled_at).is_(None),
            )
            result: Result[tuple[UserORM]] = await session.execute(statement)
            row: UserORM | None = result.scalar_one_or_none()
        if row is None or not verify_password(password, row.password_hash):
            return None
        return self._to_user(row)

    async def create_session(self, user: User) -> tuple[WebSession, str]:
        """Create a browser session and return its one-time raw token."""
        raw_token: str = generate_session_token()
        now: datetime = datetime.now(UTC)
        expires_at: datetime = now + timedelta(seconds=self._session_ttl_seconds)
        row: WebSessionORM = WebSessionORM(
            id=uuid4(),
            token_hash=hash_session_token(raw_token),
            user_id=user.id,
            created_at=now,
            last_seen_at=now,
            expires_at=expires_at,
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
        return self._to_web_session(row), raw_token

    async def resolve_session(self, raw_token: str) -> User | None:
        """Resolve and refresh a non-expired browser session."""
        token_hash: str = hash_session_token(raw_token)
        now: datetime = datetime.now(UTC)
        expires_at: datetime = now + timedelta(seconds=self._session_ttl_seconds)
        async with self._database.session() as session:
            statement: Select[tuple[UserORM]] = (
                select(UserORM)
                .join(
                    WebSessionORM,
                    col(WebSessionORM.user_id) == col(UserORM.id),
                )
                .where(
                    col(WebSessionORM.token_hash) == token_hash,
                    col(WebSessionORM.expires_at) > now,
                    col(UserORM.disabled_at).is_(None),
                )
            )
            result: Result[tuple[UserORM]] = await session.execute(statement)
            user_row: UserORM | None = result.scalar_one_or_none()
            if user_row is None:
                return None
            refresh_statement: Update = (
                update(WebSessionORM)
                .where(col(WebSessionORM.token_hash) == token_hash)
                .values(last_seen_at=now, expires_at=expires_at)
            )
            await session.execute(refresh_statement)
            await session.commit()
        return self._to_user(user_row)

    async def revoke_session(self, raw_token: str) -> bool:
        """Delete one browser session."""
        token_hash: str = hash_session_token(raw_token)
        async with self._database.session() as session:
            result: CursorResult[object] = cast(
                CursorResult[object],
                await session.execute(
                    delete(WebSessionORM).where(
                        col(WebSessionORM.token_hash) == token_hash
                    )
                )
            )
            await session.commit()
        return result.rowcount > 0

    async def list_users(self) -> list[User]:
        """Return all users ordered by creation date."""
        async with self._database.session() as session:
            statement: Select[tuple[UserORM]] = select(UserORM).order_by(
                col(UserORM.created_at).desc()
            )
            result: Result[tuple[UserORM]] = await session.execute(statement)
            rows: list[UserORM] = list(result.scalars().all())
        return [self._to_user(row) for row in rows]

    async def get_user(self, user_id: UUID) -> User | None:
        """Return a user by ID."""
        async with self._database.session() as session:
            row: UserORM | None = await session.get(UserORM, user_id)
        return self._to_user(row) if row is not None else None

    async def create_user(
        self, username: str, password: str, is_admin: bool = False
    ) -> User:
        """Create a new user with hashed password."""
        row: UserORM = UserORM(
            id=uuid4(),
            username=username,
            password_hash=hash_password(password),
            is_admin=is_admin,
            created_at=datetime.now(UTC),
        )
        async with self._database.session() as session:
            session.add(row)
            await session.commit()
        return self._to_user(row)

    async def update_user(
        self,
        user_id: UUID,
        *,
        password: str | None = None,
        is_admin: bool | None = None,
        disabled: bool | None = None,
    ) -> User | None:
        """Update user fields; return updated user or None if not found."""
        async with self._database.session() as session:
            row: UserORM | None = await session.get(UserORM, user_id)
            if row is None:
                return None
            if password is not None:
                row.password_hash = hash_password(password)
            if is_admin is not None:
                row.is_admin = is_admin
            if disabled is not None:
                row.disabled_at = datetime.now(UTC) if disabled else None
            session.add(row)
            await session.commit()
        return self._to_user(row)

    @staticmethod
    def _to_user(row: UserORM) -> User:
        return User(
            id=row.id,
            username=row.username,
            password_hash=row.password_hash,
            is_admin=row.is_admin,
            created_at=row.created_at,
            disabled_at=row.disabled_at,
        )

    @staticmethod
    def _to_web_session(row: WebSessionORM) -> WebSession:
        return WebSession(
            id=row.id,
            token_hash=row.token_hash,
            user_id=row.user_id,
            created_at=row.created_at,
            last_seen_at=row.last_seen_at,
            expires_at=row.expires_at,
        )
