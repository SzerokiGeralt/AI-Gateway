"""Wspólne dependencies: DB, Redis, autoryzacja użytkownika."""
from typing import AsyncGenerator
from uuid import UUID

import redis.asyncio as redis_async
from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.security import decode_access_token
from app.db.base import AsyncSessionLocal
from app.models.user import User, UserRole

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login", auto_error=True)


# ============================================================
# Database session
# ============================================================
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """Daje sesję AsyncSession i zamyka ją po requeście."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        finally:
            await session.close()


# ============================================================
# Redis
# ============================================================
_redis_client: redis_async.Redis | None = None


def get_redis() -> redis_async.Redis:
    """Zwraca singleton Redis client (lazy init)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = redis_async.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
        )
    return _redis_client


# ============================================================
# Autoryzacja
# ============================================================
async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
    r: redis_async.Redis = Depends(get_redis),
) -> User:
    """
    Walidacja JWT + sprawdzenie czy sesja nie została unieważniona w Redis.
    """
    credentials_error = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Nieprawidłowe dane uwierzytelniające",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = decode_access_token(token)
        user_id_str: str | None = payload.get("sub")
        if user_id_str is None:
            raise credentials_error
    except JWTError:
        raise credentials_error

    # Sprawdź czy sesja jest aktywna w Redis (logout = klucz usunięty)
    session_key = f"session:{user_id_str}"
    stored_token = await r.get(session_key)
    if stored_token is None or stored_token != token:
        raise credentials_error

    try:
        user_uuid = UUID(user_id_str)
    except ValueError:
        raise credentials_error

    result = await db.execute(select(User).where(User.id == user_uuid))
    user = result.scalar_one_or_none()
    if user is None:
        raise credentials_error
    return user


async def require_admin(
    current_user: User = Depends(get_current_user),
) -> User:
    """Tylko ADMIN — w przeciwnym razie 403."""
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Wymagane uprawnienia administratora",
        )
    return current_user
