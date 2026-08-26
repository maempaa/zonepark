"""Operación: abrir, cotizar, cobrar y anular tickets.

Tres cosas de este módulo merecen atención porque son las que evitan
cobrar de más, de menos o dos veces.

**El cobro es idempotente por naturaleza.** El operario trabaja en una
caseta con mala señal: pulsa "cobrar", no ve respuesta y vuelve a pulsar.
`cerrar_ticket` bloquea la fila del ticket y, si ya estaba cerrado,
devuelve lo que se cobró la primera vez en lugar de cobrar otra vez. La
cabecera `Idempotency-Key` es una segunda red por si el reintento llega
por otro camino.

**La cotización del cobro usa un único instante.** Se calcula `salida`
una sola vez y ese mismo valor se guarda: si se leyera el reloj dos
veces, el importe cobrado y el registrado podrían no coincidir.

**Lo que se cobra sale del snapshot del ticket, no de las tablas.** Aunque
el administrador cambie las tarifas mientras el carro está adentro.
"""

import re
import uuid
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.pricing.modelos import Cotizacion, ItemCobrado
from app.domain.pricing.motor import cotizar
from app.domain.pricing.snapshot import congelar, descongelar
from app.models.catalogo import ServiceItem, VehicleType
from app.models.parking_lot import ParkingLot
from app.models.tenant import Tenant
from app.models.ticket import (
    Charge,
    EstadoTicket,
    MetodoPago,
    Payment,
    Ticket,
    TicketItem,
)
from app.services.caja import turno_abierto_de
from app.services.tarifas import festivos_entre, plan_vigente, reglas_del_plan


class PlacaConTicketAbierto(Exception):
    """D6: se advierte, no se bloquea. El operario decide."""

    def __init__(self, ticket: Ticket) -> None:
        self.ticket = ticket
        super().__init__(
            f"La placa {ticket.placa} ya tiene el ticket {ticket.codigo} abierto"
        )


class PlacaInvalida(ValueError):
    pass


class TicketNoOperable(Exception):
    def __init__(self, detalle: str) -> None:
        super().__init__(detalle)


class PagoInsuficiente(ValueError):
    def __init__(self, recibido: Decimal, total: Decimal) -> None:
        super().__init__(f"Recibiste {recibido} y el total es {total}")


# ── Placas ───────────────────────────────────────────────────────────────

def normalizar_placa(valor: str | None) -> str | None:
    """Mayúsculas y sin separadores: 'abc-123' y 'ABC 123' son la misma placa."""
    if valor is None:
        return None
    limpia = re.sub(r"[^A-Za-z0-9]", "", valor).upper()
    return limpia or None


def _validar_placa(tipo: VehicleType, placa: str | None) -> str | None:
    if not tipo.requiere_placa:
        return placa  # se guarda si viene, pero no se exige

    if not placa:
        raise PlacaInvalida(f"Un {tipo.nombre.lower()} necesita placa")
    if tipo.patron_placa and not re.fullmatch(tipo.patron_placa, placa):
        raise PlacaInvalida(f"La placa {placa} no tiene el formato esperado")
    return placa


# ── Contexto de cálculo ──────────────────────────────────────────────────

async def zona_de_sede(session: AsyncSession, tenant: Tenant, sede: ParkingLot) -> ZoneInfo:
    """La aritmética de tarifas va en la hora de la sede, no la del servidor."""
    return ZoneInfo(sede.timezone or tenant.timezone)


async def _cotizar(
    session: AsyncSession,
    *,
    tenant: Tenant,
    ticket: Ticket,
    sede: ParkingLot,
    hasta: datetime,
) -> Cotizacion:
    zona = await zona_de_sede(session, tenant, sede)
    items = [
        ItemCobrado(i.codigo, i.nombre, i.precio_unitario, i.cantidad) for i in ticket.items
    ]
    festivos = await festivos_entre(
        session,
        desde=ticket.entrada_at.astimezone(zona).date(),
        hasta=hasta.astimezone(zona).date(),
    )
    return cotizar(
        reglas=descongelar(ticket.rate_snapshot),
        entrada=ticket.entrada_at,
        salida=hasta,
        zona=zona,
        items=items,
        festivos=festivos,
    )


# ── Abrir ────────────────────────────────────────────────────────────────

async def buscar_abierto_con_placa(
    session: AsyncSession, *, parking_lot_id: uuid.UUID, placa: str
) -> Ticket | None:
    return await session.scalar(
        select(Ticket).where(
            Ticket.parking_lot_id == parking_lot_id,
            Ticket.estado == EstadoTicket.ABIERTO,
            Ticket.placa == placa,
        )
    )


async def _siguiente_consecutivo(session: AsyncSession, sede: ParkingLot) -> int:
    """Reserva el siguiente número de la sede.

    El UPDATE ... RETURNING bloquea la fila hasta el commit, así que dos
    ingresos simultáneos en la misma sede no pueden llevarse el mismo
    número. Es el único punto serializado de la operación, y una caseta
    registra unos pocos ingresos por minuto: no hay contención real.
    """
    numero = await session.scalar(
        update(ParkingLot)
        .where(ParkingLot.id == sede.id)
        .values(ultimo_consecutivo=ParkingLot.ultimo_consecutivo + 1)
        .returning(ParkingLot.ultimo_consecutivo)
    )
    return int(numero)


async def abrir_ticket(
    session: AsyncSession,
    *,
    tenant: Tenant,
    sede: ParkingLot,
    tipo: VehicleType,
    placa: str | None,
    entrada: datetime,
    membership_id: uuid.UUID | None,
    forzar: bool = False,
    observaciones: str | None = None,
) -> Ticket:
    placa = _validar_placa(tipo, normalizar_placa(placa))

    if placa and not forzar:
        # D6: advertir, no bloquear. Casi siempre es la placa mal digitada
        # la primera vez, no un segundo vehículo.
        existente = await buscar_abierto_con_placa(
            session, parking_lot_id=sede.id, placa=placa
        )
        if existente is not None:
            raise PlacaConTicketAbierto(existente)

    zona = await zona_de_sede(session, tenant, sede)
    plan = await plan_vigente(
        session, parking_lot_id=sede.id, cuando=entrada.astimezone(zona).date()
    )
    reglas = await reglas_del_plan(session, plan=plan, vehicle_type_id=tipo.id)

    numero = await _siguiente_consecutivo(session, sede)
    ticket = Ticket(
        tenant_id=tenant.id,
        parking_lot_id=sede.id,
        vehicle_type_id=tipo.id,
        numero=numero,
        codigo=f"{sede.ticket_prefix}-{numero:06d}",
        placa=placa,
        entrada_at=entrada,
        estado=EstadoTicket.ABIERTO,
        operario_entrada_id=membership_id,
        rate_snapshot=congelar(
            reglas, plan_codigo=plan.codigo, plan_version=plan.version
        ),
        observaciones=observaciones,
    )
    session.add(ticket)
    await session.flush()
    # En SQLAlchemy async un objeto recién insertado no puede cargar sus
    # relaciones por acceso a atributo: no hay greenlet donde esperar la
    # consulta. El refresh las trae con los cargadores del mapeo.
    await session.refresh(ticket)
    return ticket


# ── Artículos ────────────────────────────────────────────────────────────

async def agregar_item(
    session: AsyncSession,
    *,
    tenant: Tenant,
    ticket: Ticket,
    articulo: ServiceItem,
    cantidad: int = 1,
) -> TicketItem:
    if ticket.estado is not EstadoTicket.ABIERTO:
        raise TicketNoOperable("El ticket ya no está abierto")

    # El precio se congela aquí: subirlo mañana no debe recalcular hacia atrás.
    item = TicketItem(
        tenant_id=tenant.id,
        ticket_id=ticket.id,
        service_item_id=articulo.id,
        codigo=articulo.codigo,
        nombre=articulo.nombre,
        precio_unitario=articulo.precio,
        cantidad=cantidad,
    )
    session.add(item)
    await session.flush()
    await session.refresh(ticket)
    return item


# ── Cotizar sin cerrar ───────────────────────────────────────────────────

async def cotizar_ticket(
    session: AsyncSession, *, tenant: Tenant, ticket: Ticket, ahora: datetime
) -> Cotizacion:
    """Lo que costaría salir en este instante. No modifica nada."""
    if ticket.estado is EstadoTicket.ANULADO:
        raise TicketNoOperable("El ticket está anulado")

    sede = await session.get(ParkingLot, ticket.parking_lot_id)
    hasta = ticket.salida_at or ahora
    return await _cotizar(session, tenant=tenant, ticket=ticket, sede=sede, hasta=hasta)


# ── Cobrar ───────────────────────────────────────────────────────────────

async def _bloquear_ticket(session: AsyncSession, ticket_id: uuid.UUID) -> Ticket | None:
    """Relee el ticket con la fila bloqueada.

    Sin esto, dos peticiones de cobro simultáneas podrían pasar las dos por
    la comprobación de estado antes de que ninguna la escribiera.
    """
    return await session.scalar(
        select(Ticket).where(Ticket.id == ticket_id).with_for_update()
    )


async def cerrar_ticket(
    session: AsyncSession,
    *,
    tenant: Tenant,
    ticket_id: uuid.UUID,
    metodo: MetodoPago,
    ahora: datetime,
    membership_id: uuid.UUID | None,
    recibido: Decimal | None = None,
    referencia: str | None = None,
    idempotency_key: str | None = None,
) -> tuple[Ticket, Payment, bool]:
    """Cierra el ticket y registra el cobro.

    Devuelve `(ticket, pago, ya_estaba_cerrado)`. El tercer valor permite a
    la API responder 200 en vez de 201 cuando fue un reintento.
    """
    ticket = await _bloquear_ticket(session, ticket_id)
    if ticket is None:
        raise TicketNoOperable("No existe ese ticket")
    if ticket.estado is EstadoTicket.ANULADO:
        raise TicketNoOperable("El ticket está anulado")

    if ticket.estado is EstadoTicket.CERRADO:
        # Reintento: se devuelve lo que ya se cobró, sin tocar nada.
        pago = await session.scalar(select(Payment).where(Payment.ticket_id == ticket.id))
        return ticket, pago, True

    if idempotency_key:
        previo = await session.scalar(
            select(Payment).where(Payment.idempotency_key == idempotency_key)
        )
        if previo is not None:
            anterior = await session.get(Ticket, previo.ticket_id)
            return anterior, previo, True

    sede = await session.get(ParkingLot, ticket.parking_lot_id)

    # Un único instante para cobrar y para registrar: si se leyera el reloj
    # dos veces, el importe y el registro podrían discrepar.
    salida = ahora
    cotizacion = await _cotizar(session, tenant=tenant, ticket=ticket, sede=sede, hasta=salida)

    if cotizacion.total == 0:
        metodo = MetodoPago.CORTESIA
        recibido = None

    cambio = None
    if metodo is MetodoPago.EFECTIVO and recibido is not None:
        if recibido < cotizacion.total:
            raise PagoInsuficiente(recibido, cotizacion.total)
        cambio = recibido - cotizacion.total

    for orden, linea in enumerate(cotizacion.lineas):
        session.add(
            Charge(
                tenant_id=tenant.id,
                ticket_id=ticket.id,
                orden=orden,
                concepto=linea.concepto,
                detalle=linea.detalle,
                monto=linea.monto,
            )
        )

    # Se ata el cobro al turno abierto del operario, si lo hay. Cobrar sin
    # turno no se bloquea —sería dejar al operario tirado a mitad de
    # jornada— pero el resumen del turno lo señala aparte.
    turno = None
    if membership_id is not None:
        turno = await turno_abierto_de(
            session, parking_lot_id=ticket.parking_lot_id, membership_id=membership_id
        )

    pago = Payment(
        tenant_id=tenant.id,
        ticket_id=ticket.id,
        cash_shift_id=turno.id if turno else None,
        metodo=metodo,
        monto=cotizacion.total,
        subtotal=cotizacion.subtotal,
        impuesto=cotizacion.impuesto,
        recibido=recibido,
        cambio=cambio,
        referencia=referencia,
        idempotency_key=idempotency_key,
    )
    session.add(pago)

    ticket.salida_at = salida
    ticket.estado = EstadoTicket.CERRADO
    ticket.operario_salida_id = membership_id

    await session.flush()
    await session.refresh(ticket)
    return ticket, pago, False


# ── Anular ───────────────────────────────────────────────────────────────

async def anular_ticket(
    session: AsyncSession, *, ticket_id: uuid.UUID, motivo: str, membership_id: uuid.UUID | None
) -> Ticket:
    ticket = await _bloquear_ticket(session, ticket_id)
    if ticket is None:
        raise TicketNoOperable("No existe ese ticket")
    if ticket.estado is EstadoTicket.CERRADO:
        raise TicketNoOperable("Un ticket ya cobrado no se anula: hay que hacer una devolución")
    if ticket.estado is EstadoTicket.ANULADO:
        return ticket

    ticket.estado = EstadoTicket.ANULADO
    ticket.anulacion_motivo = motivo
    ticket.operario_salida_id = membership_id
    await session.flush()
    return ticket


# ── Búsqueda ─────────────────────────────────────────────────────────────

async def buscar_tickets(
    session: AsyncSession,
    *,
    sedes: frozenset[uuid.UUID] | None,
    estado: EstadoTicket | None = None,
    placa: str | None = None,
    limite: int = 50,
) -> list[Ticket]:
    """Búsqueda del operario.

    La placa se busca por coincidencia parcial a propósito: en la caseta se
    teclean los últimos tres dígitos, no la placa entera.
    """
    consulta = select(Ticket).order_by(Ticket.entrada_at.desc()).limit(limite)

    if sedes is not None:
        consulta = consulta.where(Ticket.parking_lot_id.in_(sedes))
    if estado is not None:
        consulta = consulta.where(Ticket.estado == estado)
    if placa:
        # La placa y el código se buscan con términos distintos a propósito:
        # la placa se normaliza (sin guiones ni espacios) porque así está
        # guardada, pero el código sí los lleva —"S1-000002"— y normalizarlo
        # dejaría de encontrarlo.
        crudo = placa.strip().upper()
        fragmento = normalizar_placa(placa)

        condiciones = [func.upper(Ticket.codigo).contains(crudo)]
        if fragmento:
            condiciones.append(Ticket.placa.contains(fragmento))
        consulta = consulta.where(or_(*condiciones))

    return list((await session.scalars(consulta)).all())
