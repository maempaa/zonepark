"""A dónde mandarle el recibo de cada placa.

Cuelga de `ticket:create` y `ticket:read` y no de un permiso propio: quien
registra ingresos y consulta tickets ya ve la placa y el teléfono al
mandar el recibo. Un permiso aparte daría la ilusión de una barrera que
no existe.
"""

from fastapi import APIRouter, Depends, HTTPException, Path, status

from app.deps import IdentidadDep, SesionDep, TenantDep, requiere
from app.schemas.contacto import ContactoIn, ContactoOut
from app.services import audit
from app.services.contactos import (
    CorreoInvalido,
    SinDondeMandarlo,
    TelefonoInvalido,
    contacto_de,
    olvidar,
    recordar,
)

router = APIRouter(prefix="/contactos", tags=["contactos"])

_PLACA = Path(min_length=1, max_length=16)


@router.get("/{placa}", response_model=ContactoOut)
async def ver_contacto(
    session: SesionDep,
    placa: str = _PLACA,
    _: None = Depends(requiere("ticket:read")),
) -> ContactoOut:
    contacto = await contacto_de(session, placa=placa)
    if contacto is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Esa placa no tiene contacto guardado"
        )
    return contacto


@router.put("/{placa}", response_model=ContactoOut)
async def recordar_contacto(
    datos: ContactoIn,
    tenant: TenantDep,
    session: SesionDep,
    placa: str = _PLACA,
    _: None = Depends(requiere("ticket:create")),
) -> ContactoOut:
    try:
        return await recordar(
            session, tenant=tenant, placa=placa,
            telefono=datos.telefono, correo=datos.correo,
        )
    except (TelefonoInvalido, CorreoInvalido, SinDondeMandarlo) as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e


@router.delete("/{placa}", status_code=status.HTTP_204_NO_CONTENT)
async def olvidar_contacto(
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    placa: str = _PLACA,
    _: None = Depends(requiere("ticket:create")),
) -> None:
    """Borra el contacto. Es el derecho del cliente a que no lo guarden."""
    if not await olvidar(session, placa=placa):
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, "Esa placa no tiene contacto guardado"
        )
    await audit.registrar(
        session,
        accion="contacto.delete",
        entidad="plate_contact",
        entidad_id=None,
        tenant_id=tenant.id,
        actor_user_id=identidad.user_id,
        antes={"placa": placa},
    )
