"""Bitácora de auditoría.

Se escribe en la misma transacción que la acción auditada: si la acción se
deshace, su registro también. Un log que sobreviviera a un rollback estaría
mintiendo.
"""

import uuid
from typing import Any

from fastapi import Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog


def _ip_de(request: Request | None) -> str | None:
    if request is None:
        return None
    # Detrás del proxy de Astro la IP real llega en X-Forwarded-For.
    reenviada = request.headers.get("x-forwarded-for")
    if reenviada:
        return reenviada.split(",")[0].strip()[:45]
    return request.client.host[:45] if request.client else None


async def registrar(
    session: AsyncSession,
    *,
    accion: str,
    entidad: str,
    tenant_id: uuid.UUID | None = None,
    entidad_id: str | uuid.UUID | None = None,
    actor_user_id: uuid.UUID | None = None,
    actor_email: str | None = None,
    antes: dict[str, Any] | None = None,
    despues: dict[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    session.add(
        AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
            accion=accion,
            entidad=entidad,
            entidad_id=str(entidad_id) if entidad_id else None,
            antes=antes,
            despues=despues,
            ip=_ip_de(request),
            user_agent=(request.headers.get("user-agent") or "")[:300] if request else None,
        )
    )
