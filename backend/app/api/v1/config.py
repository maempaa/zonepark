"""Datos del parqueadero: nombre y el aviso que ve el cliente en su recibo.

Va aparte de `sedes` porque son del tenant entero: la política de objetos
perdidos no cambia entre una caseta y otra de la misma empresa.
"""

from fastapi import APIRouter, Depends, Request

from app.deps import IdentidadDep, SesionDep, TenantDep, requiere
from app.models.tenant import Tenant
from app.schemas.config import ConfigOut, ConfigUpdate
from app.services import audit
from app.services.recibo import TERMINOS_POR_DEFECTO

router = APIRouter(prefix="/config", tags=["configuracion"])


def _salida(tenant: Tenant) -> ConfigOut:
    return ConfigOut(
        nombre=tenant.nombre,
        terminos_condiciones=tenant.terminos_condiciones,
        terminos_efectivos=tenant.terminos_condiciones or TERMINOS_POR_DEFECTO,
        timezone=tenant.timezone,
        currency=tenant.currency,
    )


@router.get("", response_model=ConfigOut)
async def ver_config(
    tenant: TenantDep,
    _: None = Depends(requiere("tenant:read")),
) -> ConfigOut:
    return _salida(tenant)


@router.patch("", response_model=ConfigOut)
async def editar_config(
    datos: ConfigUpdate,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("tenant:update")),
) -> ConfigOut:
    cambios = datos.model_dump(exclude_unset=True)
    antes = {c: getattr(tenant, c) for c in cambios}

    # El tenant lo cargó `cargar_tenant` fuera de esta sesión; hay que
    # traerlo a ella para que el UPDATE salga de verdad.
    vivo = await session.get(Tenant, tenant.id)
    for campo, valor in cambios.items():
        if campo == "terminos_condiciones" and valor is not None:
            valor = valor.strip() or None
        setattr(vivo, campo, valor)
    await session.flush()

    await audit.registrar(
        session,
        accion="config.update",
        entidad="tenant",
        entidad_id=tenant.id,
        tenant_id=tenant.id,
        actor_user_id=identidad.user_id,
        antes=antes,
        despues=cambios,
        request=request,
    )
    return _salida(vivo)
