"""Esquemas del panel de plataforma."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.models.tenant import TenantStatus

SLUG = r"^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$"


class LoginPlataformaIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1)


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    nombre: str
    is_active: bool
    last_login_at: datetime | None


class ClienteNuevoIn(BaseModel):
    """Todo lo necesario para que un parqueadero pueda operar desde el minuto uno."""

    slug: str = Field(min_length=3, max_length=63, pattern=SLUG)
    nombre: str = Field(min_length=2, max_length=160)
    razon_social: str | None = Field(default=None, max_length=200)
    nit: str | None = Field(default=None, max_length=32)

    sede_codigo: str = Field(default="S1", min_length=1, max_length=32)
    sede_nombre: str = Field(default="Sede principal", min_length=2, max_length=160)

    admin_email: EmailStr
    admin_nombre: str = Field(min_length=2, max_length=160)
    # Doce caracteres: es la cuenta que puede cambiar tarifas y ver la caja.
    admin_password: str = Field(min_length=12, max_length=128)

    @field_validator("slug")
    @classmethod
    def _sin_reservados(cls, v: str) -> str:
        # `admin` y `api` chocarían con rutas del propio sistema.
        if v in {"admin", "api", "t", "estado", "login"}:
            raise ValueError(f"'{v}' está reservado; elige otro identificador")
        return v


class TenantResumenOut(BaseModel):
    id: uuid.UUID
    slug: str
    nombre: str
    status: str
    sedes: int
    usuarios: int
    adentro: int


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    nombre: str
    razon_social: str | None
    nit: str | None
    timezone: str
    currency: str
    status: TenantStatus
    created_at: datetime


class TenantPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=2, max_length=160)
    razon_social: str | None = Field(default=None, max_length=200)
    nit: str | None = Field(default=None, max_length=32)
    status: TenantStatus | None = None


class MiembroOut(BaseModel):
    user_id: uuid.UUID
    membership_id: uuid.UUID
    email: str
    nombre: str
    roles: list[str]
    activo: bool


class MiembroNuevoIn(BaseModel):
    email: EmailStr
    nombre: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=128)
    rol: str = Field(default="tenant_admin", max_length=32)


class AdminNuevoIn(BaseModel):
    email: EmailStr
    nombre: str = Field(min_length=2, max_length=160)
    password: str = Field(min_length=12, max_length=128)
