"""Resolución del tenant.

D1: el tenant viaja en la ruta, `/t/{slug}/...`.

Esta es *la* pieza aislada del plan: pasar a subdominios
(`cliente.zonepark.app`) es cambiar `slug_desde_peticion` y nada más. El
resto del sistema solo conoce el objeto `Tenant` que sale de aquí.
"""

from fastapi import Request
from sqlalchemy import select

from app.db.session import system_scope
from app.models.tenant import Tenant, TenantStatus


class TenantNoEncontrado(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"No existe el parqueadero '{slug}'")


class TenantSuspendido(Exception):
    def __init__(self, slug: str) -> None:
        self.slug = slug
        super().__init__(f"El parqueadero '{slug}' está suspendido")


def slug_desde_peticion(request: Request) -> str | None:
    """Extrae el slug del tenant.

    Modo `path` (actual): del parámetro de ruta `tenant_slug`.
    Para migrar a subdominios, leer aquí `request.headers['host']`.
    """
    valor = request.path_params.get("tenant_slug")
    return valor.lower() if isinstance(valor, str) else None


async def cargar_tenant(slug: str) -> Tenant:
    """Busca el tenant por slug.

    Va por `system_scope` porque todavía no hay tenant que fijar: es
    justamente la consulta que lo determina.
    """
    async with system_scope() as session:
        tenant = await session.scalar(select(Tenant).where(Tenant.slug == slug))

    if tenant is None:
        raise TenantNoEncontrado(slug)
    if tenant.status is TenantStatus.SUSPENDIDO:
        raise TenantSuspendido(slug)
    return tenant
