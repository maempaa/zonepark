"""Esquemas de entrada y salida de autenticación."""

import uuid
from datetime import datetime

from pydantic import BaseModel, EmailStr, Field


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)
    # Huella del dispositivo; si viene y la sede lo permite, queda registrado
    # para poder entrar luego solo con el PIN.
    device_fingerprint: str | None = Field(default=None, max_length=128)
    device_nombre: str | None = Field(default=None, max_length=80)


class PinLoginIn(BaseModel):
    email: EmailStr
    pin: str = Field(min_length=4, max_length=12)
    device_fingerprint: str = Field(max_length=128)


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_at: datetime
    refresh_token: str
    refresh_expires_at: datetime


class SedeOut(BaseModel):
    id: uuid.UUID
    codigo: str
    nombre: str


class MeOut(BaseModel):
    user_id: uuid.UUID
    email: str
    nombre: str
    tenant_slug: str
    tenant_nombre: str
    membership_id: uuid.UUID | None
    roles: list[str]
    permisos: list[str]
    # Nulo = todas las sedes del tenant.
    sedes: list[uuid.UUID] | None
    tiene_pin: bool
