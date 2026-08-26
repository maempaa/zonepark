"""Reportes de ocupación e ingresos.

Todo se agrega en SQL, no en Python: un parqueadero con un año de
operación tiene cientos de miles de tickets y traerlos para sumarlos en
memoria no escala.

Las fechas se agrupan en la **hora de la sede**. Un turno que termina a la
1 de la mañana pertenece al día anterior para quien lo trabajó, y agrupar
en UTC lo partiría en dos.
"""

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.caja import CashShift, EstadoTurno
from app.models.catalogo import VehicleType
from app.models.parking_lot import ParkingLot
from app.models.ticket import EstadoTicket, Payment, Ticket

CERO = Decimal("0.00")


@dataclass(slots=True)
class FilaOcupacion:
    parking_lot_id: uuid.UUID
    sede: str
    vehicle_type_id: uuid.UUID
    tipo: str
    adentro: int


@dataclass(slots=True)
class FilaDia:
    dia: date
    tickets: int
    total: Decimal


@dataclass(slots=True)
class FilaConcepto:
    concepto: str
    tickets: int
    total: Decimal


@dataclass(slots=True)
class Ingresos:
    desde: date
    hasta: date
    total: Decimal
    tickets: int
    por_dia: list[FilaDia]
    por_metodo: list[FilaConcepto]
    por_tipo: list[FilaConcepto]


def _dia_local(columna, zona: str):
    """La fecha de la columna expresada en la hora de la sede."""
    return cast(func.timezone(zona, columna), Date)


def _limitar_sedes(consulta, sedes: frozenset[uuid.UUID] | None):
    return consulta if sedes is None else consulta.where(Ticket.parking_lot_id.in_(sedes))


# ── Ocupación ────────────────────────────────────────────────────────────

async def ocupacion(
    session: AsyncSession, *, sedes: frozenset[uuid.UUID] | None
) -> list[FilaOcupacion]:
    """Qué hay adentro ahora mismo, por sede y tipo de vehículo."""
    consulta = (
        select(
            ParkingLot.id,
            ParkingLot.nombre,
            VehicleType.id,
            VehicleType.nombre,
            func.count(Ticket.id),
        )
        .select_from(Ticket)
        .join(ParkingLot, ParkingLot.id == Ticket.parking_lot_id)
        .join(VehicleType, VehicleType.id == Ticket.vehicle_type_id)
        .where(Ticket.estado == EstadoTicket.ABIERTO)
        .group_by(ParkingLot.id, ParkingLot.nombre, VehicleType.id, VehicleType.nombre)
        .order_by(ParkingLot.nombre, VehicleType.nombre)
    )
    filas = (await session.execute(_limitar_sedes(consulta, sedes))).all()
    return [FilaOcupacion(*fila) for fila in filas]


# ── Ingresos ─────────────────────────────────────────────────────────────

async def ingresos(
    session: AsyncSession,
    *,
    sedes: frozenset[uuid.UUID] | None,
    desde: date,
    hasta: date,
    zona: str,
) -> Ingresos:
    """Lo cobrado en un rango de fechas, desglosado.

    Se cuenta por la fecha de **salida**: es cuando entró el dinero.
    """
    dia = _dia_local(Ticket.salida_at, zona)

    por_dia_q = _limitar_sedes(
        select(dia, func.count(Payment.id), func.coalesce(func.sum(Payment.monto), CERO))
        .select_from(Payment)
        .join(Ticket, Ticket.id == Payment.ticket_id)
        .where(Ticket.estado == EstadoTicket.CERRADO, dia >= desde, dia <= hasta)
        .group_by(dia)
        .order_by(dia),
        sedes,
    )
    por_metodo_q = _limitar_sedes(
        select(Payment.metodo, func.count(Payment.id), func.coalesce(func.sum(Payment.monto), CERO))
        .select_from(Payment)
        .join(Ticket, Ticket.id == Payment.ticket_id)
        .where(Ticket.estado == EstadoTicket.CERRADO, dia >= desde, dia <= hasta)
        .group_by(Payment.metodo)
        .order_by(func.sum(Payment.monto).desc()),
        sedes,
    )
    por_tipo_q = _limitar_sedes(
        select(
            VehicleType.nombre,
            func.count(Payment.id),
            func.coalesce(func.sum(Payment.monto), CERO),
        )
        .select_from(Payment)
        .join(Ticket, Ticket.id == Payment.ticket_id)
        .join(VehicleType, VehicleType.id == Ticket.vehicle_type_id)
        .where(Ticket.estado == EstadoTicket.CERRADO, dia >= desde, dia <= hasta)
        .group_by(VehicleType.nombre)
        .order_by(func.sum(Payment.monto).desc()),
        sedes,
    )

    filas_dia = [FilaDia(d, n, t) for d, n, t in (await session.execute(por_dia_q)).all()]
    filas_metodo = [
        FilaConcepto(str(m), n, t) for m, n, t in (await session.execute(por_metodo_q)).all()
    ]
    filas_tipo = [
        FilaConcepto(nombre, n, t) for nombre, n, t in (await session.execute(por_tipo_q)).all()
    ]

    return Ingresos(
        desde=desde,
        hasta=hasta,
        total=sum((f.total for f in filas_dia), CERO),
        tickets=sum(f.tickets for f in filas_dia),
        por_dia=filas_dia,
        por_metodo=filas_metodo,
        por_tipo=filas_tipo,
    )


# ── Turnos ───────────────────────────────────────────────────────────────

async def turnos_del_rango(
    session: AsyncSession,
    *,
    sedes: frozenset[uuid.UUID] | None,
    desde: datetime | None = None,
    hasta: datetime | None = None,
    solo_abiertos: bool = False,
    limite: int = 100,
) -> list[CashShift]:
    consulta = select(CashShift).order_by(CashShift.abierto_at.desc()).limit(limite)
    if sedes is not None:
        consulta = consulta.where(CashShift.parking_lot_id.in_(sedes))
    if solo_abiertos:
        consulta = consulta.where(CashShift.estado == EstadoTurno.ABIERTO)
    if desde is not None:
        consulta = consulta.where(CashShift.abierto_at >= desde)
    if hasta is not None:
        consulta = consulta.where(CashShift.abierto_at <= hasta)
    return list((await session.scalars(consulta)).all())


async def descuadres(
    session: AsyncSession, *, sedes: frozenset[uuid.UUID] | None, limite: int = 20
) -> list[CashShift]:
    """Turnos cerrados que no cuadraron. Lo primero que mira el dueño."""
    consulta = (
        select(CashShift)
        .where(CashShift.estado == EstadoTurno.CERRADO, CashShift.diferencia != CERO)
        .order_by(func.abs(CashShift.diferencia).desc())
        .limit(limite)
    )
    if sedes is not None:
        consulta = consulta.where(CashShift.parking_lot_id.in_(sedes))
    return list((await session.scalars(consulta)).all())


# ── Exportación ──────────────────────────────────────────────────────────

def ingresos_a_csv(datos: Ingresos) -> str:
    """CSV con separador de coma y punto decimal, para abrir en cualquier parte."""
    lineas = ["seccion,concepto,tickets,total"]
    for f in datos.por_dia:
        lineas.append(f"dia,{f.dia.isoformat()},{f.tickets},{f.total}")
    for f in datos.por_metodo:
        lineas.append(f"metodo,{f.concepto},{f.tickets},{f.total}")
    for f in datos.por_tipo:
        lineas.append(f"tipo,{f.concepto},{f.tickets},{f.total}")
    lineas.append(f"total,,{datos.tickets},{datos.total}")
    return "\n".join(lineas) + "\n"
