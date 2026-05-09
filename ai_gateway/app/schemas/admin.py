"""Schematy panelu administracyjnego."""
from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from app.models.user import UserRole


class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=64)
    password: str = Field(..., min_length=8, max_length=256)
    role: UserRole = UserRole.USER
    department: Optional[str] = Field(default=None, max_length=128)


class UserUpdate(BaseModel):
    role: Optional[UserRole] = None
    department: Optional[str] = Field(default=None, max_length=128)
    password: Optional[str] = Field(default=None, min_length=8, max_length=256)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    role: UserRole
    department: Optional[str] = None
    created_at: datetime


class IncidentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    original_prompt: str
    sanitized_prompt: str
    reason: str
    created_at: datetime


class PolicyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    content: str
    uploaded_by: Optional[UUID] = None
    updated_at: datetime


class SmtpToConfig(BaseModel):
    smtp_to: str = Field(default="", max_length=254)


class SmtpToResponse(BaseModel):
    smtp_to: str
