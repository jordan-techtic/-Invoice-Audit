from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from .models import Role


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(ORM):
    id: uuid.UUID
    email: str
    name: str
    role: Role
    is_active: bool


class UserCreate(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=200)
    password: str = Field(min_length=12)
    role: Role = Role.analyst
    client_ids: list[uuid.UUID] = []


class ClientOut(ORM):
    id: uuid.UUID
    name: str
    slug: str
    inbound_email_token: str
    settings: dict
    service_offer_text: str | None
    audit_completed_at: datetime | None
    created_at: datetime


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    settings: dict | None = None
    service_offer_text: str | None = None
