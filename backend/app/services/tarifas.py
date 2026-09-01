"""Resolución del plan tarifario vigente.

La pregunta que responde este módulo es: "para esta sede, este tipo de
vehículo y este momento, ¿qué reglas aplican?". La respuesta alimenta al
motor y, cuando se abre un ticket, se congela dentro de él.
"""

import uuid
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.pricing.modelos import ReglaTarifaria
from app.domain.pricing.snapshot import reglas_de
from app.models.catalogo import Holiday, VehicleType
from app.models.tarifa import EstadoPlan, RatePlan, RateRule


class SinPlanVigente(LookupError):
    def __init__(self, cuando: date) -> None:
        super().__init__(f"No hay un plan tarifario activo para el {cuando:%Y-%m-%d}")


class SinTarifaParaElVehiculo(LookupError):
    def __init__(self, codigo: str) -> None:
        super().__init__(f"El plan activo no tiene tarifa para '{codigo}'")


async def plan_vigente(
    session: AsyncSession,
    *,
    parking_lot_id: uuid.UUID,
    cuando: date,
) -> RatePlan:
    """El plan activo para esa sede en esa fecha.

    Un plan específico de la sede le gana al plan general del tenant: así
    una sede con tarifas propias no obliga a duplicar todo el catálogo.
    A igualdad, gana la versión más alta.
    """
    consulta = (
        select(RatePlan)
        .where(
            RatePlan.estado == EstadoPlan.ACTIVO,
            or_(RatePlan.parking_lot_id == parking_lot_id, RatePlan.parking_lot_id.is_(None)),
            or_(RatePlan.vigente_desde.is_(None), RatePlan.vigente_desde <= cuando),
            or_(RatePlan.vigente_hasta.is_(None), RatePlan.vigente_hasta >= cuando),
        )
        # nulls_last: los planes de sede van primero.
        .order_by(RatePlan.parking_lot_id.is_(None), RatePlan.version.desc())
        .limit(1)
    )
    plan = await session.scalar(consulta)
    if plan is None:
        raise SinPlanVigente(cuando)
    return plan


async def reglas_del_plan(
    session: AsyncSession,
    *,
    plan: RatePlan,
    vehicle_type_id: uuid.UUID,
) -> list[ReglaTarifaria]:
    """Todas las reglas de ese tipo de vehículo dentro del plan.

    Se devuelven todas —base, nocturna, festiva— porque es el motor quien
    decide cuál aplica a cada tramo de la estadía.
    """
    filas = list(
        (
            await session.scalars(
                select(RateRule).where(
                    RateRule.rate_plan_id == plan.id,
                    RateRule.vehicle_type_id == vehicle_type_id,
                    # Las apagadas conservan su precio pero no se cobran.
                    RateRule.activa.is_(True),
                )
            )
        ).all()
    )
    if not filas:
        tipo = await session.get(VehicleType, vehicle_type_id)
        raise SinTarifaParaElVehiculo(tipo.codigo if tipo else str(vehicle_type_id))
    return reglas_de(filas)


async def festivos_entre(
    session: AsyncSession, *, desde: date, hasta: date
) -> frozenset[date]:
    fechas = await session.scalars(
        select(Holiday.fecha).where(Holiday.fecha >= desde, Holiday.fecha <= hasta)
    )
    return frozenset(fechas.all())
