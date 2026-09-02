"""Las tarifas entre las que elige el operario al recibir un vehículo.

Es una lectura del plan vigente, no del ticket: cuando se consulta, el
ticket todavía no existe. Por eso no puede reutilizar `opciones_de_cobro`,
que cotiza sobre un ticket ya abierto.

Se devuelven todos los tipos de vehículo de una vez. La pantalla de ingreso
cambia de tipo con un toque y volver al servidor en cada cambio se sentiría
lento en la caseta, que es donde se usa.
"""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select

from app.deps import IdentidadDep, SesionDep, TenantDep, requiere
from app.domain.pricing.modelos import ModoCobro, ReglaTarifaria
from app.models.catalogo import VehicleType
from app.models.parking_lot import ParkingLot
from app.schemas.tarifa_ingreso import OpcionIngresoOut, TarifasDeTipoOut
from app.services.tarifas import (
    SinPlanVigente,
    SinTarifaParaElVehiculo,
    plan_vigente,
    reglas_del_plan,
)
from app.services.tickets import _nombre_de

router = APIRouter(prefix="/tarifas", tags=["tarifas"])


def _pesos(v) -> str:
    return f"${v:,.0f}".replace(",", ".")


def _descripcion(r: ReglaTarifaria) -> str:
    """Una línea que le diga al operario qué está eligiendo."""
    if r.modo is ModoCobro.POR_MINUTO:
        return f"{_pesos(r.precio_minuto)} por minuto"
    if r.modo is ModoCobro.POR_BLOQUE:
        unidad = "hora" if r.bloque_minutos == 60 else f"{r.bloque_minutos} min"
        return f"{_pesos(r.precio_bloque)} por {unidad}, fracción completa"
    if r.modo is ModoCobro.PRIMER_BLOQUE_LUEGO_MINUTO:
        return (
            f"{_pesos(r.precio_bloque)} el primer bloque, "
            f"luego {_pesos(r.precio_minuto)} por minuto"
        )
    if r.modo is ModoCobro.PLENA:
        return f"{_pesos(r.precio_plena)} sin importar el tiempo"
    if r.modo is ModoCobro.POR_DIA:
        return f"{_pesos(r.precio_dia)} por día empezado"
    if r.modo is ModoCobro.ESCALONADO:
        return "Precio por tramos"
    return ""


@router.get("/ingreso", response_model=list[TarifasDeTipoOut])
async def tarifas_de_ingreso(
    parking_lot_id: uuid.UUID,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    _: None = Depends(requiere("rate:read")),
) -> list[TarifasDeTipoOut]:
    if identidad.sedes is not None and parking_lot_id not in identidad.sedes:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe esa sede")
    sede = await session.get(ParkingLot, parking_lot_id)
    if sede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe esa sede")

    try:
        plan = await plan_vigente(
            session, parking_lot_id=sede.id, cuando=datetime.now(UTC).date()
        )
    except SinPlanVigente:
        # Sin plan no hay nada que elegir; la pantalla de ingreso ya avisa
        # cuando el cobro no se puede calcular.
        return []

    tipos = await session.scalars(
        select(VehicleType).where(VehicleType.activo.is_(True)).order_by(VehicleType.orden)
    )

    salida: list[TarifasDeTipoOut] = []
    for tipo in tipos:
        try:
            reglas = await reglas_del_plan(session, plan=plan, vehicle_type_id=tipo.id)
        except SinTarifaParaElVehiculo:
            # Un tipo sin tarifa no se puede ingresar; no se ofrece aquí en
            # vez de romper la pantalla entera por uno mal configurado.
            continue
        sueltas = [r for r in reglas if r.franja is None]
        if not sueltas:
            continue

        # La predeterminada tiene que ser una sola, y tiene que ser la
        # misma que el motor elegiría solo: por eso se desempata igual que
        # él, por prioridad y luego por código. Los planes anteriores a que
        # se pudiera marcar una tienen todas las reglas en prioridad 0, y
        # sin este desempate saldrían varias marcadas a la vez.
        predeterminada = min(sueltas, key=lambda r: (-r.prioridad, r.codigo)).codigo
        salida.append(
            TarifasDeTipoOut(
                vehicle_type_id=tipo.id,
                # Con franjas configuradas hay que poder dejar que el motor
                # decida: la nocturna y la de festivo no entran por ninguna
                # otra vía, y forzar una tarifa fija las anularía sin avisar.
                admite_automatica=any(r.franja is not None for r in reglas),
                opciones=[
                    OpcionIngresoOut(
                        codigo=r.codigo,
                        nombre=_nombre_de(r),
                        descripcion=_descripcion(r),
                        predeterminada=r.codigo == predeterminada,
                    )
                    for r in sueltas
                ],
            )
        )
    return salida
