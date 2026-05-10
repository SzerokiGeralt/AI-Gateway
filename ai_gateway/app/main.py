"""Główny punkt wejścia aplikacji FastAPI."""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from sqlalchemy import select

from app.api import admin as admin_router
from app.api import auth as auth_router
from app.api import chat as chat_router
from app.core.config import settings
from app.core.dependencies import get_current_user
from app.core.rate_limit import limiter
from app.core.security import hash_password
from app.db.base import AsyncSessionLocal
from app.models.user import User, UserRole
from app.services import classifier_service, presidio_service

logging.basicConfig(
    level=logging.INFO if not settings.DEBUG else logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(name)s :: %(message)s",
)
logger = logging.getLogger(__name__)


# ============================================================
# Lifespan — seed początkowego admina
# ============================================================
async def _seed_initial_admin() -> None:
    """Tworzy konto admina przy pierwszym starcie, jeśli nie istnieje."""
    if not settings.INITIAL_ADMIN_USERNAME or not settings.INITIAL_ADMIN_PASSWORD:
        return

    async with AsyncSessionLocal() as session:
        existing = await session.execute(
            select(User).where(User.username == settings.INITIAL_ADMIN_USERNAME)
        )
        if existing.scalar_one_or_none() is not None:
            return
        admin = User(
            username=settings.INITIAL_ADMIN_USERNAME,
            hashed_password=hash_password(settings.INITIAL_ADMIN_PASSWORD),
            role=UserRole.ADMIN,
        )
        session.add(admin)
        await session.commit()
        logger.info(
            "Utworzono początkowe konto administratora '%s'",
            settings.INITIAL_ADMIN_USERNAME,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Uruchamianie %s (env=%s)", settings.APP_NAME, settings.APP_ENV)
    try:
        await _seed_initial_admin()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "Seed admina nie powiódł się (DB jeszcze niegotowa?): %s", exc
        )

    # Pre-load modeli DLP (spaCy + klasyfikator) - inaczej pierwszy /chat ma kilkusekundowe opoznienie.
    try:
        presidio_service.warmup()
        classifier_service.warmup()
    except Exception as exc:  # noqa: BLE001
        # Fail-closed dziala na poziomie requestu - tutaj tylko sygnal.
        logger.error("Warmup DLP nie powiodl sie: %s", exc)

    yield
    logger.info("Zamykanie aplikacji")


# ============================================================
# App
# ============================================================
app = FastAPI(
    title=settings.APP_NAME,
    debug=settings.DEBUG,
    lifespan=lifespan,
)

# Rate limiter (slowapi)
app.state.limiter = limiter


@app.exception_handler(RateLimitExceeded)
async def _rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return JSONResponse(
        status_code=429,
        content={"detail": f"Przekroczony limit zapytań: {exc.detail}"},
    )


# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Routery
app.include_router(auth_router.router)
app.include_router(admin_router.router)
app.include_router(chat_router.router)


# ============================================================
# Meta endpointy
# ============================================================
@app.get("/health", tags=["meta"])
async def health() -> dict:
    return {"status": "ok", "app": settings.APP_NAME}


@app.get("/me", tags=["meta"])
async def me(current_user: User = Depends(get_current_user)) -> dict:
    return {
        "id": str(current_user.id),
        "username": current_user.username,
        "role": current_user.role.value,
        "department": current_user.department,
    }
