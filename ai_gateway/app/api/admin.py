"""Endpointy panelu administracyjnego."""
from typing import List
from uuid import UUID

import redis.asyncio as redis_async
from fastapi import (
    APIRouter,
    Depends,
    File,
    HTTPException,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db, get_redis, require_admin
from app.core.security import hash_password
from app.models.incident import SecurityIncident
from app.models.policy import CompanyPolicy
from app.models.user import User, UserRole
from app.schemas.admin import (
    IncidentOut,
    PolicyOut,
    SmtpToConfig,
    SmtpToResponse,
    UserCreate,
    UserOut,
    UserUpdate,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


# ============================================================
# Users CRUD
# ============================================================
@router.get("/users", response_model=List[UserOut])
async def list_users(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> List[User]:
    result = await db.execute(
        select(User).order_by(User.created_at.desc()).offset(skip).limit(limit)
    )
    return list(result.scalars().all())


@router.post("/users", response_model=UserOut, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    db: AsyncSession = Depends(get_db),
) -> User:
    user = User(
        username=payload.username,
        hashed_password=hash_password(payload.password),
        role=payload.role,
        department=payload.department,
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Użytkownik o takiej nazwie już istnieje",
        )
    await db.refresh(user)
    return user


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: UUID,
    payload: UserUpdate,
    db: AsyncSession = Depends(get_db),
) -> User:
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brak użytkownika")

    if payload.role is not None:
        user.role = payload.role
    if payload.department is not None:
        user.department = payload.department
    if payload.password is not None:
        user.hashed_password = hash_password(payload.password)

    await db.commit()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}")
async def delete_user(
    user_id: UUID,
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> Response:
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Nie możesz usunąć własnego konta",
        )
    result = await db.execute(delete(User).where(User.id == user_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brak użytkownika")
    await db.commit()
    return Response(status_code=204)


# ============================================================
# Policy
# ============================================================
@router.get("/policy", response_model=PolicyOut)
async def get_current_policy(
    db: AsyncSession = Depends(get_db),
) -> CompanyPolicy:
    result = await db.execute(
        select(CompanyPolicy).order_by(CompanyPolicy.updated_at.desc()).limit(1)
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brak polityki")
    return policy


@router.get("/policy/download")
async def download_policy(
    db: AsyncSession = Depends(get_db),
) -> Response:
    """Pobiera aktualną politykę DLP jako plik .txt."""
    result = await db.execute(
        select(CompanyPolicy).order_by(CompanyPolicy.updated_at.desc()).limit(1)
    )
    policy = result.scalar_one_or_none()
    if policy is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brak polityki")
    return Response(
        content=policy.content.encode("utf-8"),
        media_type="text/plain; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="dlp_policy.txt"'},
    )


@router.post("/policy", response_model=PolicyOut, status_code=status.HTTP_201_CREATED)
async def upload_policy(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_admin: User = Depends(require_admin),
) -> CompanyPolicy:
    """
    Przyjmuje plik .txt (multipart/form-data, pole `file`) i zapisuje
    jego treść jako nową aktywną politykę firmową.
    """
    if not file.filename or not file.filename.lower().endswith(".txt"):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Wymagany plik .txt",
        )

    raw = await file.read()
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plik musi być zakodowany w UTF-8",
        )

    if not content.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Plik polityki jest pusty",
        )

    policy = CompanyPolicy(content=content, uploaded_by=current_admin.id)
    db.add(policy)
    await db.commit()
    await db.refresh(policy)
    return policy


# ============================================================
# SMTP config (recipient email stored in Redis)
# ============================================================
_SMTP_TO_KEY = "config:smtp_to"


@router.get("/config/smtp-to", response_model=SmtpToResponse)
async def get_smtp_to(
    r: redis_async.Redis = Depends(get_redis),
) -> SmtpToResponse:
    value = await r.get(_SMTP_TO_KEY)
    return SmtpToResponse(smtp_to=value or settings.SMTP_TO or "")


@router.put("/config/smtp-to", response_model=SmtpToResponse)
async def set_smtp_to(
    payload: SmtpToConfig,
    r: redis_async.Redis = Depends(get_redis),
) -> SmtpToResponse:
    if payload.smtp_to:
        await r.set(_SMTP_TO_KEY, payload.smtp_to)
    else:
        await r.delete(_SMTP_TO_KEY)
    return SmtpToResponse(smtp_to=payload.smtp_to)


# ============================================================
# Incidents
# ============================================================
@router.get("/incidents", response_model=List[IncidentOut])
async def list_incidents(
    db: AsyncSession = Depends(get_db),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> List[SecurityIncident]:
    result = await db.execute(
        select(SecurityIncident)
        .order_by(SecurityIncident.created_at.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(result.scalars().all())


@router.delete("/incidents/{incident_id}")
async def delete_incident(
    incident_id: UUID,
    db: AsyncSession = Depends(get_db),
) -> Response:
    result = await db.execute(
        delete(SecurityIncident).where(SecurityIncident.id == incident_id)
    )
    if result.rowcount == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Brak incydentu")
    await db.commit()
    return Response(status_code=204)