"""Turnos de caja y arqueo.

El arqueo responde una sola pregunta: **¿cuadra el cajón?** Todo lo demás
de este módulo existe para que ese número signifique algo.

## Qué entra en el esperado

    esperado = base inicial
             + efectivo cobrado en tickets del turno
             + movimientos de ingreso
             − movimientos de egreso

Solo efectivo. Una tarjeta o un QR no llegan al cajón, así que sumarlos
haría que todos los turnos aparecieran descuadrados. Se reportan aparte.

De un cobro en efectivo se suma el **monto**, no lo que entregó el
cliente: los $5.000 con los que paga un servicio de $1.000 dejan $1.000
en la caja, porque los otros $4.000 salieron como cambio.

## Cobros sin turno

Si el operario cobra en efectivo sin haber abierto turno, el pago se
registra igual —no se le bloquea el trabajo a mitad de jornada— pero
queda sin turno asignado. El resumen del turno lo señala aparte para que
el dueño lo vea, en vez de que desaparezca.
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.caja import CashMovement, CashShift, EstadoTurno, TipoMovimiento
from app.models.parking_lot import ParkingLot
from app.models.tenant import Tenant
from app.models.ticket import MetodoPago, Payment, Ticket

CERO = Decimal("0.00")


class TurnoYaAbierto(Exception):
    def __init__(self, turno: CashShift) -> None:
        self.turno = turno
        super().__init__("Ya tienes un turno abierto en esta sede")


class TurnoNoOperable(Exception):
    pass


@dataclass(slots=True)
class Arqueo:
    """El corte de caja de un turno."""

    base_inicial: Decimal
    efectivo_cobrado: Decimal
    ingresos_manuales: Decimal
    egresos_manuales: Decimal
    esperado: Decimal

    contado: Decimal | None = None
    diferencia: Decimal | None = None

    tickets_cobrados: int = 0
    por_metodo: dict[str, Decimal] = field(default_factory=dict)
    # Efectivo cobrado en la sede durante el turno pero sin turno asignado.
    efectivo_sin_turno: Decimal = CERO

    @property
    def cuadra(self) -> bool:
        return self.diferencia == CERO if self.diferencia is not None else False


# ── Turno vigente ────────────────────────────────────────────────────────

async def turno_abierto_de(
    session: AsyncSession, *, parking_lot_id: uuid.UUID, membership_id: uuid.UUID
) -> CashShift | None:
    return await session.scalar(
        select(CashShift).where(
            CashShift.parking_lot_id == parking_lot_id,
            CashShift.membership_id == membership_id,
            CashShift.estado == EstadoTurno.ABIERTO,
        )
    )


# ── Apertura ─────────────────────────────────────────────────────────────

async def abrir_turno(
    session: AsyncSession,
    *,
    tenant: Tenant,
    sede: ParkingLot,
    membership_id: uuid.UUID,
    base_inicial: Decimal,
    ahora: datetime,
    notas: str | None = None,
) -> CashShift:
    existente = await turno_abierto_de(
        session, parking_lot_id=sede.id, membership_id=membership_id
    )
    if existente is not None:
        raise TurnoYaAbierto(existente)

    turno = CashShift(
        tenant_id=tenant.id,
        parking_lot_id=sede.id,
        membership_id=membership_id,
        abierto_at=ahora,
        base_inicial=base_inicial,
        notas_apertura=notas,
    )
    session.add(turno)
    await session.flush()
    await session.refresh(turno)
    return turno


# ── Movimientos ──────────────────────────────────────────────────────────

async def registrar_movimiento(
    session: AsyncSession,
    *,
    tenant: Tenant,
    turno: CashShift,
    tipo: TipoMovimiento,
    concepto: str,
    monto: Decimal,
    membership_id: uuid.UUID | None,
) -> CashMovement:
    if turno.estado is not EstadoTurno.ABIERTO:
        raise TurnoNoOperable("El turno ya está cerrado")
    if monto <= 0:
        raise ValueError("El monto debe ser mayor que cero; el signo lo pone el tipo")

    movimiento = CashMovement(
        tenant_id=tenant.id,
        cash_shift_id=turno.id,
        membership_id=membership_id,
        tipo=tipo,
        concepto=concepto,
        monto=monto,
    )
    session.add(movimiento)
    await session.flush()
    await session.refresh(turno)
    return movimiento


# ── Arqueo ───────────────────────────────────────────────────────────────

async def calcular_arqueo(session: AsyncSession, *, turno: CashShift) -> Arqueo:
    """Lo que la caja debería tener. No modifica nada."""
    filas = (
        await session.execute(
            select(Payment.metodo, func.sum(Payment.monto), func.count())
            .where(Payment.cash_shift_id == turno.id)
            .group_by(Payment.metodo)
        )
    ).all()

    por_metodo = {str(metodo): (suma or CERO) for metodo, suma, _ in filas}
    tickets = sum(cuantos for _, _, cuantos in filas)
    efectivo = por_metodo.get(str(MetodoPago.EFECTIVO), CERO)

    ingresos = CERO
    egresos = CERO
    for m in turno.movimientos:
        if m.tipo is TipoMovimiento.INGRESO:
            ingresos += m.monto
        else:
            egresos += m.monto

    # Efectivo cobrado en esta sede durante la ventana del turno pero sin
    # turno asignado: el hueco que el dueño necesita ver.
    hasta = turno.cerrado_at or datetime.now(turno.abierto_at.tzinfo)
    huerfano = await session.scalar(
        select(func.coalesce(func.sum(Payment.monto), CERO))
        .join(Ticket, Ticket.id == Payment.ticket_id)
        .where(
            Ticket.parking_lot_id == turno.parking_lot_id,
            Payment.cash_shift_id.is_(None),
            Payment.metodo == MetodoPago.EFECTIVO,
            Payment.created_at >= turno.abierto_at,
            Payment.created_at <= hasta,
        )
    )

    esperado = turno.base_inicial + efectivo + ingresos - egresos

    return Arqueo(
        base_inicial=turno.base_inicial,
        efectivo_cobrado=efectivo,
        ingresos_manuales=ingresos,
        egresos_manuales=egresos,
        esperado=esperado,
        contado=turno.contado,
        diferencia=turno.diferencia,
        tickets_cobrados=tickets,
        por_metodo=por_metodo,
        efectivo_sin_turno=huerfano or CERO,
    )


async def cerrar_turno(
    session: AsyncSession,
    *,
    turno: CashShift,
    contado: Decimal,
    ahora: datetime,
    notas: str | None = None,
) -> Arqueo:
    """Cierra el turno y congela el arqueo.

    `esperado` se guarda, no se recalcula después: si una anulación
    posterior cambiara el número, el turno ya cuadrado dejaría de cuadrar
    sin que nadie hubiera tocado el cajón.
    """
    if turno.estado is not EstadoTurno.ABIERTO:
        raise TurnoNoOperable("El turno ya está cerrado")

    turno.cerrado_at = ahora
    arqueo = await calcular_arqueo(session, turno=turno)

    turno.esperado = arqueo.esperado
    turno.contado = contado
    turno.diferencia = contado - arqueo.esperado
    turno.estado = EstadoTurno.CERRADO
    turno.notas_cierre = notas
    await session.flush()

    arqueo.contado = turno.contado
    arqueo.diferencia = turno.diferencia
    return arqueo
