"""Dependencias de FastAPI: tenant, sesión, identidad y permisos."""

import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import TokenInvalido, leer_token_de_acceso
from app.core.tenancy import (
    TenantNoEncontrado,
    TenantSuspendido,
    cargar_tenant,
    slug_desde_peticion,
)
from app.db.session import tenant_scope
from app.models.tenant import Tenant

_bearer = HTTPBearer(auto_error=False)


# ── Tenant ───────────────────────────────────────────────────────────────

async def obtener_tenant(request: Request) -> Tenant:
    slug = slug_desde_peticion(request)
    if not slug:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Falta el parqueadero en la ruta")
    try:
        return await cargar_tenant(slug)
    except TenantNoEncontrado as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
    except TenantSuspendido as e:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(e)) from e


TenantDep = Annotated[Tenant, Depends(obtener_tenant)]


# ── Sesión de base de datos ──────────────────────────────────────────────

async def obtener_sesion(tenant: TenantDep) -> AsyncGenerator[AsyncSession, None]:
    async with tenant_scope(tenant.id) as session:
        yield session


SesionDep = Annotated[AsyncSession, Depends(obtener_sesion)]


# ── Identidad ────────────────────────────────────────────────────────────

@dataclass(slots=True)
class Identidad:
    user_id: uuid.UUID
    tenant_id: uuid.UUID | None
    membership_id: uuid.UUID | None
    permisos: frozenset[str] = field(default_factory=frozenset)
    # None = todas las sedes del tenant.
    sedes: frozenset[uuid.UUID] | None = None
    es_admin_plataforma: bool = False

    def puede(self, permiso: str) -> bool:
        return permiso in self.permisos

    def alcanza_sede(self, parking_lot_id: uuid.UUID) -> bool:
        return self.sedes is None or parking_lot_id in self.sedes


def _credenciales_invalidas(detalle: str) -> HTTPException:
    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detalle,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def obtener_identidad(
    tenant: TenantDep,
    credenciales: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> Identidad:
    if credenciales is None:
        raise _credenciales_invalidas("Falta el token de acceso")

    try:
        payload = leer_token_de_acceso(credenciales.credentials)
    except TokenInvalido as e:
        raise _credenciales_invalidas(str(e)) from e

    # El claim del token manda sobre la ruta: si no coinciden, se rechaza.
    # Sin esto, un token de un tenant serviría en la URL de otro.
    tid = payload.get("tid")
    if tid != str(tenant.id):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            "El token no corresponde a este parqueadero",
        )

    sedes = payload.get("lots")
    return Identidad(
        user_id=uuid.UUID(payload["sub"]),
        tenant_id=tenant.id,
        membership_id=uuid.UUID(payload["mem"]) if payload.get("mem") else None,
        permisos=frozenset(payload.get("perms") or []),
        sedes=frozenset(uuid.UUID(s) for s in sedes) if sedes is not None else None,
        es_admin_plataforma=bool(payload.get("plat")),
    )


IdentidadDep = Annotated[Identidad, Depends(obtener_identidad)]


# ── Permisos ─────────────────────────────────────────────────────────────

def requiere(*permisos: str):
    """Dependencia que exige todos los permisos indicados.

    Uso: `dependencies=[Depends(requiere("rate:manage"))]`
    """

    async def _verificar(identidad: IdentidadDep) -> Identidad:
        faltantes = [p for p in permisos if not identidad.puede(p)]
        if faltantes:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Te falta el permiso {', '.join(faltantes)}",
            )
        return identidad

    return _verificar
