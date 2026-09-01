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
from dataclasses import dataclass, replace
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.pricing.modelos import (
    Cotizacion,
    ItemCobrado,
    LineaCargo,
    ModoCobro,
    ReglaTarifaria,
)
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


class OpcionDesconocida(ValueError):
    def __init__(self, codigo: str) -> None:
        super().__init__(f"'{codigo}' no es una opción de cobro de este ticket")


class MotivoRequerido(ValueError):
    """Un monto puesto a mano sin explicación no se puede auditar."""

    def __init__(self) -> None:
        super().__init__("Escribe por qué cambias el valor")


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
    reglas: list[ReglaTarifaria] | None = None,
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
        reglas=reglas if reglas is not None else descongelar(ticket.rate_snapshot),
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


# ── Opciones de cobro ────────────────────────────────────────────────────
# Un parqueadero no cobra siempre igual. Al mismo carro se le puede
# aplicar la tarifa por hora, una plena de todo el día o un convenio, y
# quien cobra decide en el momento con el cliente delante.
#
# La primera opción es la que calcula el motor con todas las reglas, que
# es la que respeta las franjas nocturnas y de festivo. Las demás son cada
# regla por separado: si el operario elige una a mano, se aplica esa y ya,
# sin franjas, porque eligió un precio concreto y no un comportamiento.


@dataclass(slots=True)
class OpcionCobro:
    codigo: str
    nombre: str
    recomendada: bool
    cotizacion: Cotizacion


def _nombre_de(regla: ReglaTarifaria) -> str:
    if regla.nombre:
        return regla.nombre
    etiquetas = {
        ModoCobro.POR_MINUTO: "Por minuto",
        ModoCobro.POR_BLOQUE: (
            "Por hora" if regla.bloque_minutos == 60
            else f"Por fracción de {regla.bloque_minutos} min"
        ),
        ModoCobro.PRIMER_BLOQUE_LUEGO_MINUTO: "Primer bloque y luego minutos",
        ModoCobro.ESCALONADO: "Escalonada",
        ModoCobro.PLENA: "Tarifa plena",
        ModoCobro.POR_DIA: "Por día",
        ModoCobro.MENSUALIDAD: "Mensualidad",
    }
    return etiquetas.get(regla.modo, regla.codigo)


async def opciones_de_cobro(
    session: AsyncSession, *, tenant: Tenant, ticket: Ticket, ahora: datetime
) -> list[OpcionCobro]:
    """Las formas en que se le puede cobrar a este ticket, ya cotizadas."""
    if ticket.estado is EstadoTicket.ANULADO:
        raise TicketNoOperable("El ticket está anulado")

    sede = await session.get(ParkingLot, ticket.parking_lot_id)
    hasta = ticket.salida_at or ahora
    reglas = descongelar(ticket.rate_snapshot)

    automatica = await _cotizar(session, tenant=tenant, ticket=ticket, sede=sede, hasta=hasta)
    opciones = [
        OpcionCobro(
            codigo=automatica.regla_aplicada,
            nombre=_nombre_de(
                next(r for r in reglas if r.codigo == automatica.regla_aplicada)
            ),
            recomendada=True,
            cotizacion=automatica,
        )
    ]

    vistas = {(opciones[0].nombre, opciones[0].cotizacion.total)}

    for regla in reglas:
        if regla.codigo == automatica.regla_aplicada:
            continue
        # Las reglas con franja —la nocturna, la de festivo— no son una
        # elección de quien cobra: son variantes horarias que ya aplica la
        # automática. Ofrecerlas sueltas mostraría dos opciones idénticas
        # sin forma de distinguirlas.
        if regla.franja is not None:
            continue
        suelta = replace(regla, prioridad=0)
        try:
            cotizacion = await _cotizar(
                session, tenant=tenant, ticket=ticket, sede=sede, hasta=hasta,
                reglas=[suelta],
            )
        except (ValueError, LookupError, NotImplementedError):
            # Una regla que no sabe cotizar —una mensualidad, por ejemplo—
            # no se ofrece en vez de romper la pantalla de cobro.
            continue
        # Dos opciones que se llaman igual y cuestan lo mismo no son dos
        # opciones: son una pregunta sin respuesta para quien cobra.
        nombre = _nombre_de(regla)
        if (nombre, cotizacion.total) in vistas:
            continue
        vistas.add((nombre, cotizacion.total))

        opciones.append(
            OpcionCobro(
                codigo=regla.codigo,
                nombre=nombre,
                recomendada=False,
                cotizacion=cotizacion,
            )
        )

    return opciones


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
    opcion: str | None = None,
    monto_manual: Decimal | None = None,
    motivo_ajuste: str | None = None,
) -> tuple[Ticket, Payment, bool]:
    """Cierra el ticket y registra el cobro.

    `opcion` elige entre las formas de cobro del ticket; sin ella se aplica
    la que recomienda el motor. `monto_manual` sustituye el total calculado
    y exige un motivo: sin él, un valor puesto a mano sería indistinguible
    de uno calculado y no habría nada que auditar.

    Devuelve `(ticket, pago, ya_estaba_cerrado)`. El tercer valor permite a
    la API responder 200 en vez de 201 cuando fue un reintento.
    """
    if monto_manual is not None and not (motivo_ajuste or "").strip():
        raise MotivoRequerido()
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

    # Un único instante para cobrar y para registrar: si se leyera el reloj
    # dos veces, el importe y el registro podrían discrepar.
    salida = ahora

    # Se cotizan todas las formas de cobro y se toma la elegida. Aunque el
    # monto acabe puesto a mano, se guarda lo que el sistema calculó: es lo
    # único que permite auditar la diferencia después.
    opciones = await opciones_de_cobro(session, tenant=tenant, ticket=ticket, ahora=salida)

    if opcion:
        elegida = next((o for o in opciones if o.codigo == opcion), None)
        if elegida is None:
            raise OpcionDesconocida(opcion)
    else:
        elegida = opciones[0]

    cotizacion = elegida.cotizacion
    calculado = cotizacion.total
    lineas = list(cotizacion.lineas)
    total = calculado

    if monto_manual is not None:
        # La diferencia va como una línea más para que el desglose siga
        # sumando el total: un recibo que no cuadra no sirve de nada.
        diferencia = monto_manual - calculado
        if diferencia != 0:
            lineas.append(
                LineaCargo("Ajuste manual", diferencia, detalle=motivo_ajuste.strip()[:120])
            )
        total = monto_manual

    if total == 0:
        metodo = MetodoPago.CORTESIA
        recibido = None

    cambio = None
    if metodo is MetodoPago.EFECTIVO and recibido is not None:
        if recibido < total:
            raise PagoInsuficiente(recibido, total)
        cambio = recibido - total

    for orden, linea in enumerate(lineas):
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
        monto=total,
        # Con ajuste manual no tiene sentido conservar la descomposición
        # fiscal de una tarifa que no se aplicó.
        subtotal=cotizacion.subtotal if monto_manual is None else total,
        impuesto=cotizacion.impuesto if monto_manual is None else Decimal("0.00"),
        recibido=recibido,
        cambio=cambio,
        referencia=referencia,
        idempotency_key=idempotency_key,
        regla_aplicada=elegida.codigo,
        monto_calculado=calculado,
        ajuste_manual=monto_manual is not None,
        motivo_ajuste=motivo_ajuste.strip()[:300] if monto_manual is not None else None,
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
