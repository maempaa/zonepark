"""Sedes del tenant.

La lectura respeta el alcance del rol: un operario asignado a una sede no
ve las demás, aunque pertenezcan a su mismo tenant. RLS aísla entre
clientes; esto aísla dentro del cliente.
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from app.deps import IdentidadDep, SesionDep, TenantDep, requiere
from app.models.parking_lot import ParkingLot
from app.schemas.sede import SedeIn, SedeOut, SedeUpdate
from app.services import audit

router = APIRouter(prefix="/sedes", tags=["sedes"])


@router.get("", response_model=list[SedeOut])
async def listar_sedes(
    session: SesionDep,
    identidad: IdentidadDep,
    _: None = Depends(requiere("lot:read")),
) -> list[ParkingLot]:
    consulta = select(ParkingLot).order_by(ParkingLot.codigo)
    if identidad.sedes is not None:
        consulta = consulta.where(ParkingLot.id.in_(identidad.sedes))
    return list((await session.scalars(consulta)).all())


@router.post("", response_model=SedeOut, status_code=status.HTTP_201_CREATED)
async def crear_sede(
    datos: SedeIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("lot:manage")),
) -> ParkingLot:
    ya_existe = await session.scalar(
        select(ParkingLot).where(ParkingLot.codigo == datos.codigo)
    )
    if ya_existe is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Ya existe una sede con el código '{datos.codigo}'"
        )

    sede = ParkingLot(
        tenant_id=tenant.id,
        codigo=datos.codigo,
        nombre=datos.nombre,
        direccion=datos.direccion,
        telefono=datos.telefono,
        timezone=datos.timezone,
        device_policy=datos.device_policy,
        ticket_prefix=datos.codigo[:8].upper(),
    )
    session.add(sede)
    await session.flush()

    await audit.registrar(
        session,
        accion="sede.create",
        entidad="parking_lot",
        entidad_id=sede.id,
        tenant_id=tenant.id,
        actor_user_id=identidad.user_id,
        despues={"codigo": sede.codigo, "nombre": sede.nombre},
        request=request,
    )
    return sede


@router.patch("/{sede_id}", response_model=SedeOut)
async def editar_sede(
    sede_id: uuid.UUID,
    datos: SedeUpdate,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("lot:manage")),
) -> ParkingLot:
    sede = await session.get(ParkingLot, sede_id)
    if sede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe esa sede")
    # Un operario con alcance de sede no edita las que no le tocan.
    if identidad.sedes is not None and sede.id not in identidad.sedes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe esa sede")

    cambios = datos.model_dump(exclude_unset=True)
    antes = {c: getattr(sede, c) for c in cambios}
    for campo, valor in cambios.items():
        # Un campo en blanco es un campo vacío, no la cadena "".
        if isinstance(valor, str) and campo != "nombre":
            valor = valor.strip() or None
        setattr(sede, campo, valor)
    await session.flush()

    await audit.registrar(
        session,
        accion="sede.update",
        entidad="parking_lot",
        entidad_id=sede.id,
        tenant_id=tenant.id,
        actor_user_id=identidad.user_id,
        antes={k: str(v) if v is not None else None for k, v in antes.items()},
        despues={k: str(v) if v is not None else None for k, v in cambios.items()},
        request=request,
    )
    return sede
