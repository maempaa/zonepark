"""Planes tarifarios y simulador.

Los planes se crean en borrador, se prueban con el simulador y se activan.
Activar archiva la versión anterior en vez de sobrescribirla: un ticket
abierto hace días tiene que poder señalar con qué versión se le cotizó.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import IdentidadDep, SesionDep, TenantDep, requiere
from app.domain.pricing.modelos import Cotizacion, ItemCobrado
from app.domain.pricing.motor import SalidaAntesDeEntrada, SinReglaAplicable, cotizar
from app.domain.pricing.snapshot import reglas_de
from app.models.catalogo import ServiceItem, VehicleType
from app.models.parking_lot import ParkingLot
from app.models.tarifa import EstadoPlan, RatePlan, RateRule, RateTier
from app.models.tenant import Tenant
from app.schemas.tarifa import (
    CotizacionOut,
    PlanDetalleOut,
    PlanIn,
    PlanOut,
    ReglaIn,
    SimulacionIn,
)
from app.services import audit
from app.services.tarifas import festivos_entre

router = APIRouter(prefix="/planes", tags=["tarifas"])


async def _plan_o_404(session: AsyncSession, plan_id: uuid.UUID) -> RatePlan:
    plan = await session.get(RatePlan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe ese plan tarifario")
    return plan


async def _validar_reglas(
    session: AsyncSession, reglas: Sequence[ReglaIn]
) -> None:
    """Comprueba que los tipos existan y que no haya códigos repetidos."""
    tipos_validos = set((await session.scalars(select(VehicleType.id))).all())
    vistos: set[str] = set()
    for regla in reglas:
        if regla.vehicle_type_id not in tipos_validos:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                f"El tipo de vehículo {regla.vehicle_type_id} no existe en este parqueadero",
            )
        if regla.codigo in vistos:
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST, f"El código de regla '{regla.codigo}' está repetido"
            )
        vistos.add(regla.codigo)


def _solo_borrador(plan: RatePlan) -> None:
    if plan.estado is not EstadoPlan.BORRADOR:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Un plan activo o archivado no se edita: crea una versión nueva",
        )


def _fila_de_regla(tenant_id: uuid.UUID, plan_id: uuid.UUID, datos: ReglaIn) -> RateRule:
    regla = RateRule(
        tenant_id=tenant_id,
        rate_plan_id=plan_id,
        vehicle_type_id=datos.vehicle_type_id,
        codigo=datos.codigo,
        nombre=datos.nombre,
        modo=datos.modo,
        precio_minuto=datos.precio_minuto,
        precio_bloque=datos.precio_bloque,
        precio_plena=datos.precio_plena,
        precio_dia=datos.precio_dia,
        bloque_minutos=datos.bloque_minutos,
        dia_horas=datos.dia_horas,
        gracia_minutos=datos.gracia_minutos,
        cobro_minimo=datos.cobro_minimo,
        tope_diario=datos.tope_diario,
        tarifa_ticket_perdido=datos.tarifa_ticket_perdido,
        redondeo_modo=datos.redondeo_modo,
        redondeo_paso=datos.redondeo_paso,
        impuesto_modo=datos.impuesto_modo,
        impuesto_tasa=datos.impuesto_tasa,
        prioridad=datos.prioridad,
        tiene_franja=datos.franja is not None,
    )
    if datos.franja is not None:
        regla.franja_dias = datos.franja.dias
        regla.franja_desde = datos.franja.desde_hora
        regla.franja_hasta = datos.franja.hasta_hora
        regla.franja_incluye_festivos = datos.franja.incluye_festivos
        regla.franja_solo_festivos = datos.franja.solo_festivos

    regla.escalones = [
        RateTier(
            tenant_id=tenant_id,
            desde_minuto=e.desde_minuto,
            hasta_minuto=e.hasta_minuto,
            precio=e.precio,
            unidad=e.unidad,
            bloque_minutos=e.bloque_minutos,
        )
        for e in datos.escalones
    ]
    return regla


# ── Planes ───────────────────────────────────────────────────────────────

@router.get("", response_model=list[PlanOut])
async def listar_planes(
    session: SesionDep,
    _: None = Depends(requiere("rate:read")),
) -> list[RatePlan]:
    return list(
        (
            await session.scalars(
                select(RatePlan).order_by(RatePlan.codigo, RatePlan.version.desc())
            )
        ).all()
    )


@router.get("/{plan_id}", response_model=PlanDetalleOut)
async def ver_plan(
    plan_id: uuid.UUID,
    session: SesionDep,
    _: None = Depends(requiere("rate:read")),
) -> RatePlan:
    return await _plan_o_404(session, plan_id)


@router.post("", response_model=PlanDetalleOut, status_code=status.HTTP_201_CREATED)
async def crear_plan(
    datos: PlanIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("rate:manage")),
) -> RatePlan:
    """Crea un plan en borrador.

    Si ya existe un plan con ese código, el nuevo entra como la versión
    siguiente. No se toca el que esté activo hasta que se active este.
    """
    ultima = await session.scalar(
        select(RatePlan.version)
        .where(RatePlan.codigo == datos.codigo)
        .order_by(RatePlan.version.desc())
        .limit(1)
    )

    if datos.parking_lot_id is not None:
        sede = await session.get(ParkingLot, datos.parking_lot_id)
        if sede is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe esa sede")

    plan = RatePlan(
        tenant_id=tenant.id,
        codigo=datos.codigo,
        nombre=datos.nombre,
        version=(ultima or 0) + 1,
        estado=EstadoPlan.BORRADOR,
        parking_lot_id=datos.parking_lot_id,
        vigente_desde=datos.vigente_desde,
        vigente_hasta=datos.vigente_hasta,
    )
    session.add(plan)
    await session.flush()

    await _validar_reglas(session, datos.reglas)
    for regla in datos.reglas:
        session.add(_fila_de_regla(tenant.id, plan.id, regla))

    await session.flush()
    await session.refresh(plan)

    await audit.registrar(
        session, accion="plan_tarifario.create", entidad="rate_plan",
        entidad_id=plan.id, tenant_id=tenant.id, actor_user_id=identidad.user_id,
        despues={"codigo": plan.codigo, "version": plan.version, "reglas": len(datos.reglas)},
        request=request,
    )
    return plan


@router.post(
    "/{plan_id}/reglas",
    response_model=PlanDetalleOut,
    status_code=status.HTTP_201_CREATED,
)
async def agregar_regla(
    plan_id: uuid.UUID,
    datos: ReglaIn,
    tenant: TenantDep,
    session: SesionDep,
    _: None = Depends(requiere("rate:manage")),
) -> RatePlan:
    plan = await _plan_o_404(session, plan_id)
    _solo_borrador(plan)
    if await session.scalar(
        select(RateRule).where(RateRule.rate_plan_id == plan.id, RateRule.codigo == datos.codigo)
    ):
        raise HTTPException(status.HTTP_409_CONFLICT, f"Ya existe la regla '{datos.codigo}'")

    session.add(_fila_de_regla(tenant.id, plan.id, datos))
    await session.flush()
    await session.refresh(plan)
    return plan


@router.put("/{plan_id}/reglas", response_model=PlanDetalleOut)
async def reemplazar_reglas(
    plan_id: uuid.UUID,
    reglas: list[ReglaIn],
    tenant: TenantDep,
    session: SesionDep,
    _: None = Depends(requiere("rate:manage")),
) -> RatePlan:
    """Sustituye por completo las tarifas de un borrador.

    Es un reemplazo, no una fusión: lo que no venga en la lista se borra.
    La pantalla de tarifas trabaja así porque un plan es un conjunto
    coherente, no una colección de reglas sueltas que se parchean.
    """
    plan = await _plan_o_404(session, plan_id)
    _solo_borrador(plan)
    await _validar_reglas(session, reglas)

    for vieja in list(plan.reglas):
        await session.delete(vieja)
    await session.flush()

    for regla in reglas:
        session.add(_fila_de_regla(tenant.id, plan.id, regla))
    await session.flush()
    await session.refresh(plan)
    return plan


@router.delete("/{plan_id}", status_code=status.HTTP_204_NO_CONTENT)
async def descartar_borrador(
    plan_id: uuid.UUID,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("rate:manage")),
) -> None:
    """Descarta un borrador. Los planes activos y archivados no se borran:
    son la historia con la que se cotizaron los tickets."""
    plan = await _plan_o_404(session, plan_id)
    if plan.estado is not EstadoPlan.BORRADOR:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Solo se descartan borradores; los planes publicados son historia",
        )

    await audit.registrar(
        session, accion="plan_tarifario.discard", entidad="rate_plan",
        entidad_id=plan.id, tenant_id=tenant.id, actor_user_id=identidad.user_id,
        antes={"codigo": plan.codigo, "version": plan.version}, request=request,
    )
    await session.delete(plan)


@router.post("/{plan_id}/activar", response_model=PlanOut)
async def activar_plan(
    plan_id: uuid.UUID,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("rate:manage")),
) -> RatePlan:
    """Pone el plan en producción y archiva la versión anterior."""
    plan = await _plan_o_404(session, plan_id)
    if plan.estado is EstadoPlan.ACTIVO:
        return plan
    if plan.estado is EstadoPlan.ARCHIVADO:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Un plan archivado no se reactiva: duplícalo"
        )
    if not plan.reglas:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "El plan no tiene ninguna tarifa que aplicar"
        )

    anteriores = list(
        (
            await session.scalars(
                select(RatePlan).where(
                    RatePlan.codigo == plan.codigo,
                    RatePlan.estado == EstadoPlan.ACTIVO,
                    RatePlan.id != plan.id,
                )
            )
        ).all()
    )
    for viejo in anteriores:
        viejo.estado = EstadoPlan.ARCHIVADO

    plan.estado = EstadoPlan.ACTIVO
    await session.flush()

    await audit.registrar(
        session, accion="plan_tarifario.activate", entidad="rate_plan",
        entidad_id=plan.id, tenant_id=tenant.id, actor_user_id=identidad.user_id,
        despues={
            "codigo": plan.codigo,
            "version": plan.version,
            "archivadas": [str(v.id) for v in anteriores],
        },
        request=request,
    )
    return plan


# ── Simulador ────────────────────────────────────────────────────────────

def _a_salida(c: Cotizacion) -> CotizacionOut:
    return CotizacionOut(
        minutos=c.minutos,
        minutos_facturables=c.minutos_facturables,
        lineas=[
            {"concepto": linea.concepto, "monto": linea.monto, "detalle": linea.detalle}
            for linea in c.lineas
        ],
        subtotal=c.subtotal,
        impuesto=c.impuesto,
        ajuste_redondeo=c.ajuste_redondeo,
        total=c.total,
        regla_aplicada=c.regla_aplicada,
        en_cortesia=c.en_cortesia,
        tope_aplicado=c.tope_aplicado,
        minimo_aplicado=c.minimo_aplicado,
    )


async def _zona_de(session: AsyncSession, tenant: Tenant, lot_id: uuid.UUID | None) -> ZoneInfo:
    """La aritmética de tarifas va en la hora de la sede, no la del servidor."""
    if lot_id is not None:
        sede = await session.get(ParkingLot, lot_id)
        if sede is not None and sede.timezone:
            return ZoneInfo(sede.timezone)
    return ZoneInfo(tenant.timezone)


@router.post("/{plan_id}/simular", response_model=CotizacionOut)
async def simular(
    plan_id: uuid.UUID,
    datos: SimulacionIn,
    tenant: TenantDep,
    session: SesionDep,
    _: None = Depends(requiere("rate:read")),
) -> CotizacionOut:
    """Cotiza una estadía contra un plan, esté publicado o en borrador.

    Es la red de seguridad antes de activar: se prueban las tarifas con
    casos reales sin que ningún cliente las esté pagando todavía.
    """
    plan = await _plan_o_404(session, plan_id)

    reglas_orm = list(
        (
            await session.scalars(
                select(RateRule).where(
                    RateRule.rate_plan_id == plan.id,
                    RateRule.vehicle_type_id == datos.vehicle_type_id,
                )
            )
        ).all()
    )
    if not reglas_orm:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "Este plan no tiene tarifa para ese tipo de vehículo"
        )

    items = []
    if datos.items:
        catalogo = {
            a.codigo: a
            for a in (
                await session.scalars(
                    select(ServiceItem).where(
                        ServiceItem.codigo.in_([i.codigo for i in datos.items])
                    )
                )
            ).all()
        }
        for pedido in datos.items:
            articulo = catalogo.get(pedido.codigo)
            if articulo is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, f"No existe el artículo '{pedido.codigo}'"
                )
            items.append(
                ItemCobrado(articulo.codigo, articulo.nombre, articulo.precio, pedido.cantidad)
            )

    zona = await _zona_de(session, tenant, datos.parking_lot_id)
    entrada = datos.entrada if datos.entrada.tzinfo else datos.entrada.replace(tzinfo=UTC)
    salida = datos.salida if datos.salida.tzinfo else datos.salida.replace(tzinfo=UTC)

    festivos = await festivos_entre(
        session, desde=entrada.astimezone(zona).date(), hasta=salida.astimezone(zona).date()
    )

    try:
        cotizacion = cotizar(
            reglas=reglas_de(reglas_orm),
            entrada=entrada,
            salida=salida,
            zona=zona,
            items=items,
            festivos=festivos,
        )
    except SalidaAntesDeEntrada as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except SinReglaAplicable as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    return _a_salida(cotizacion)
