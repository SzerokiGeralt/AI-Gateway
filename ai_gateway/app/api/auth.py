"""Endpointy logowania/wylogowania."""
from __future__ import annotations

import redis.asyncio as redis_async
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_current_user, get_db, get_redis
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", response_model=TokenResponse)
async def login(
    payload: LoginRequest,
    db: AsyncSession = Depends(get_db),
    r: redis_async.Redis = Depends(get_redis),
) -> TokenResponse:
    """
    Wystawia JWT po pozytywnej weryfikacji credentiali.
    Token zapisywany jest w Redis pod kluczem `session:{user_id}` z TTL.
    """
    result = await db.execute(select(User).where(User.username == payload.username))
    user = result.scalar_one_or_none()

    if user is None or not verify_password(payload.password, user.hashed_password):
        # ujednolicony komunikat — nie zdradzamy czy user istnieje
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Nieprawidłowa nazwa użytkownika lub hasło",
        )

    token = create_access_token(subject=str(user.id), role=user.role.value)

    # Sesja w Redis z TTL = JWT_EXPIRE_MINUTES * 60
    await r.set(
        f"session:{user.id}",
        token,
        ex=settings.JWT_EXPIRE_MINUTES * 60,
    )

    return TokenResponse(access_token=token)


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    response_model=None,
)
async def logout(
    current_user: User = Depends(get_current_user),
    r: redis_async.Redis = Depends(get_redis),
) -> None:
    """Unieważnia sesję — czyści klucze Redis dla danego user_id."""
    user_id = str(current_user.id)

    # Usuń sesję
    await r.delete(f"session:{user_id}")
    # Wyczyść też historię czatu (wg instrukcji opcjonalnie)
    await r.delete(f"chat_history:{user_id}")
    return None
