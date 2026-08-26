"""Tipos de vehículo y artículos: lo que cada parqueadero define por su cuenta."""

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select

from app.deps import IdentidadDep, SesionDep, TenantDep, requiere
from app.models.catalogo import ServiceItem, VehicleType
from app.schemas.catalogo import (
    ArticuloIn,
    ArticuloOut,
    ArticuloPatch,
    TipoVehiculoIn,
    TipoVehiculoOut,
    TipoVehiculoPatch,
)
from app.services import audit

router = APIRouter(tags=["parametrización"])


# ── Tipos de vehículo ────────────────────────────────────────────────────

@router.get("/tipos-vehiculo", response_model=list[TipoVehiculoOut])
async def listar_tipos(
    session: SesionDep,
    solo_activos: bool = True,
    _: None = Depends(requiere("lot:read")),
) -> list[VehicleType]:
    consulta = select(VehicleType).order_by(VehicleType.orden, VehicleType.nombre)
    if solo_activos:
        consulta = consulta.where(VehicleType.activo.is_(True))
    return list((await session.scalars(consulta)).all())


@router.post(
    "/tipos-vehiculo", response_model=TipoVehiculoOut, status_code=status.HTTP_201_CREATED
)
async def crear_tipo(
    datos: TipoVehiculoIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("vehicle_type:manage")),
) -> VehicleType:
    if await session.scalar(select(VehicleType).where(VehicleType.codigo == datos.codigo)):
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"Ya existe el tipo '{datos.codigo}'"
        )

    tipo = VehicleType(tenant_id=tenant.id, **datos.model_dump())
    session.add(tipo)
    await session.flush()
    await audit.registrar(
        session, accion="tipo_vehiculo.create", entidad="vehicle_type",
        entidad_id=tipo.id, tenant_id=tenant.id, actor_user_id=identidad.user_id,
        despues=datos.model_dump(mode="json"), request=request,
    )
    return tipo


@router.patch("/tipos-vehiculo/{tipo_id}", response_model=TipoVehiculoOut)
async def editar_tipo(
    tipo_id: str,
    datos: TipoVehiculoPatch,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("vehicle_type:manage")),
) -> VehicleType:
    tipo = await session.get(VehicleType, tipo_id)
    if tipo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe ese tipo de vehículo")

    cambios = datos.model_dump(exclude_unset=True)
    antes = {campo: getattr(tipo, campo) for campo in cambios}
    for campo, valor in cambios.items():
        setattr(tipo, campo, valor)
    await session.flush()

    await audit.registrar(
        session, accion="tipo_vehiculo.update", entidad="vehicle_type",
        entidad_id=tipo.id, tenant_id=tenant.id, actor_user_id=identidad.user_id,
        antes={k: str(v) for k, v in antes.items()},
        despues={k: str(v) for k, v in cambios.items()},
        request=request,
    )
    return tipo


# ── Artículos y servicios ────────────────────────────────────────────────

@router.get("/articulos", response_model=list[ArticuloOut])
async def listar_articulos(
    session: SesionDep,
    solo_activos: bool = True,
    _: None = Depends(requiere("lot:read")),
) -> list[ServiceItem]:
    consulta = select(ServiceItem).order_by(ServiceItem.orden, ServiceItem.nombre)
    if solo_activos:
        consulta = consulta.where(ServiceItem.activo.is_(True))
    return list((await session.scalars(consulta)).all())


@router.post("/articulos", response_model=ArticuloOut, status_code=status.HTTP_201_CREATED)
async def crear_articulo(
    datos: ArticuloIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("service_item:manage")),
) -> ServiceItem:
    if await session.scalar(select(ServiceItem).where(ServiceItem.codigo == datos.codigo)):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ya existe el artículo '{datos.codigo}'")

    articulo = ServiceItem(tenant_id=tenant.id, **datos.model_dump())
    session.add(articulo)
    await session.flush()
    await audit.registrar(
        session, accion="articulo.create", entidad="service_item",
        entidad_id=articulo.id, tenant_id=tenant.id, actor_user_id=identidad.user_id,
        despues=datos.model_dump(mode="json"), request=request,
    )
    return articulo


@router.patch("/articulos/{articulo_id}", response_model=ArticuloOut)
async def editar_articulo(
    articulo_id: str,
    datos: ArticuloPatch,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("service_item:manage")),
) -> ServiceItem:
    articulo = await session.get(ServiceItem, articulo_id)
    if articulo is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe ese artículo")

    cambios = datos.model_dump(exclude_unset=True)
    for campo, valor in cambios.items():
        setattr(articulo, campo, valor)
    await session.flush()

    await audit.registrar(
        session, accion="articulo.update", entidad="service_item",
        entidad_id=articulo.id, tenant_id=tenant.id, actor_user_id=identidad.user_id,
        despues={k: str(v) for k, v in cambios.items()}, request=request,
    )
    return articulo
