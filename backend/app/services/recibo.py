"""El recibo que ve el cliente, sin sesión.

Lo abre quien dejó el vehículo, desde su propio celular, con el enlace que
le pasó el operario. No hay usuario detrás: la única credencial es el
token del ticket.

Eso obliga a dos disciplinas que el resto de la aplicación no necesita.

**Se devuelve lo justo.** Un ticket arrastra quién lo abrió, quién lo
cerró, contra qué turno de caja se cobró y con cuánto pagó el cliente. Al
cliente no le corresponde nada de eso, y publicarlo sería filtrar la
operación interna del parqueadero por una puerta sin llave. Este módulo
arma una vista aparte en vez de reutilizar la del operario, para que
agregar un campo allá no lo publique aquí sin querer.

**El monto es un estimado, y se dice.** Quien cobra puede elegir otra
forma de cobro o ajustar el valor a mano; mostrar el automático como si
fuera definitivo crearía la discusión que este recibo venía a evitar. Una
vez cerrado el ticket, el estimado desaparece y queda lo que se cobró.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.catalogo import VehicleType
from app.models.parking_lot import ParkingLot
from app.models.tenant import Tenant
from app.models.ticket import Charge, EstadoTicket, Payment, Ticket
from app.services.tickets import TicketNoOperable, opciones_de_cobro

AVISO_POR_DEFECTO = (
    "No nos hacemos responsables por objetos dejados dentro del vehículo, "
    "ni por accesorios exteriores. Retire sus pertenencias de valor."
)


class ReciboNoEncontrado(Exception):
    """Token que no corresponde a ningún ticket de este parqueadero."""


@dataclass(slots=True)
class LineaRecibo:
    concepto: str
    detalle: str | None
    monto: Decimal


@dataclass(slots=True)
class ReciboPublico:
    # Quién cobra
    parqueadero: str
    sede: str
    direccion: str | None
    telefono: str | None
    aviso: str

    # Qué se dejó
    codigo: str
    placa: str | None
    vehiculo: str
    entrada_at: datetime
    salida_at: datetime | None
    estado: str

    # Cuánto va
    minutos: int
    lineas: list[LineaRecibo]
    total: Decimal
    tarifa: str | None
    # La tarifa se pactó al recibir el vehículo, no la eligió el motor.
    # Cambia lo que la pantalla puede prometerle al cliente.
    acordada: bool
    estimado: bool
    en_cortesia: bool

    # Cuándo se calculó, para que la pantalla sepa qué tan fresco es
    calculado_at: datetime


async def recibo_publico(
    session: AsyncSession, *, tenant: Tenant, token: str, ahora: datetime
) -> ReciboPublico:
    ticket = await session.scalar(select(Ticket).where(Ticket.token_publico == token))
    if ticket is None:
        raise ReciboNoEncontrado("Ese recibo no existe o ya no está disponible")

    sede = await session.get(ParkingLot, ticket.parking_lot_id)
    tipo = await session.get(VehicleType, ticket.vehicle_type_id)

    base = {
        "parqueadero": tenant.nombre,
        "sede": sede.nombre if sede else tenant.nombre,
        "direccion": sede.direccion if sede else None,
        "telefono": sede.telefono if sede else None,
        "aviso": tenant.aviso_responsabilidad or AVISO_POR_DEFECTO,
        "codigo": ticket.codigo,
        "placa": ticket.placa,
        "vehiculo": tipo.nombre if tipo else "Vehículo",
        "entrada_at": ticket.entrada_at,
        "salida_at": ticket.salida_at,
        "estado": ticket.estado.value,
        "acordada": ticket.opcion_cobro is not None,
        "calculado_at": ahora,
    }

    if ticket.estado is EstadoTicket.ANULADO:
        return ReciboPublico(
            **base, minutos=0, lineas=[], total=Decimal("0.00"),
            tarifa=None, estimado=False, en_cortesia=False,
        )

    # Ya cobrado: lo que quedó registrado, no un cálculo nuevo. Recalcular
    # después del cierre daría un número distinto al que pagó.
    if ticket.estado is EstadoTicket.CERRADO:
        pago = await session.scalar(
            select(Payment).where(Payment.ticket_id == ticket.id).order_by(Payment.created_at)
        )
        # Consulta explícita, no `ticket.cargos`: la relación es perezosa y
        # cargarla dentro de un contexto async revienta con MissingGreenlet.
        cargos = await session.scalars(
            select(Charge).where(Charge.ticket_id == ticket.id).order_by(Charge.orden)
        )
        lineas = [
            LineaRecibo(concepto=c.concepto, detalle=c.detalle, monto=c.monto)
            for c in cargos
        ]
        minutos = 0
        if ticket.salida_at:
            minutos = int((ticket.salida_at - ticket.entrada_at).total_seconds() // 60)
        return ReciboPublico(
            **base,
            minutos=minutos,
            lineas=lineas,
            total=pago.monto if pago else Decimal("0.00"),
            tarifa=pago.regla_aplicada if pago else None,
            estimado=False,
            en_cortesia=False,
        )

    # Abierto: se cotiza al vuelo con la tarifa que aplicaría sola.
    try:
        opciones = await opciones_de_cobro(session, tenant=tenant, ticket=ticket, ahora=ahora)
    except TicketNoOperable as e:
        raise ReciboNoEncontrado(str(e)) from e

    recomendada = next((o for o in opciones if o.recomendada), opciones[0])
    c = recomendada.cotizacion
    return ReciboPublico(
        **base,
        minutos=c.minutos,
        lineas=[
            LineaRecibo(concepto=ln.concepto, detalle=ln.detalle, monto=ln.monto)
            for ln in c.lineas
        ],
        total=c.total,
        tarifa=recomendada.nombre,
        estimado=True,
        en_cortesia=c.en_cortesia,
    )
