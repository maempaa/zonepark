"""Esquemas de la operación."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.ticket import EstadoTicket, MetodoPago
from app.schemas.tarifa import CotizacionOut


class ItemIn(BaseModel):
    codigo: str
    cantidad: int = Field(default=1, ge=1, le=99)


class IngresoIn(BaseModel):
    parking_lot_id: uuid.UUID
    vehicle_type_id: uuid.UUID
    placa: str | None = Field(default=None, max_length=16)
    observaciones: str | None = Field(default=None, max_length=300)
    # La tarifa acordada con el cliente al recibirle el vehículo. Nulo =
    # la que aplique automáticamente, que es la única vía por la que entran
    # las franjas nocturna y de festivo.
    opcion_cobro: str | None = Field(default=None, max_length=48)
    # D6: el operario confirma que de verdad son dos ingresos distintos.
    forzar: bool = False
    # Artículos entregados en el momento del ingreso: el casco que se guarda
    # al recibir la moto, por ejemplo. Van aquí y no en una llamada aparte
    # porque el ticket y lo que se entregó tienen que nacer juntos: si el
    # segundo paso fallara, el casco quedaría entregado y sin cobrar.
    items: list[ItemIn] = Field(default_factory=list)


class CobroIn(BaseModel):
    metodo: MetodoPago = MetodoPago.EFECTIVO
    # Solo en efectivo: lo que entrega el cliente, para calcular el cambio.
    recibido: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    referencia: str | None = Field(default=None, max_length=64)

    # Con qué opción de cobro. Sin ella se aplica la recomendada.
    opcion: str | None = Field(default=None, max_length=48)
    # Sustituye el total calculado. Exige motivo: un valor puesto a mano
    # sin explicación no se puede auditar.
    monto_manual: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    motivo_ajuste: str | None = Field(default=None, max_length=300)


class AnulacionIn(BaseModel):
    motivo: str = Field(min_length=3, max_length=300)


class ItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    codigo: str
    nombre: str
    precio_unitario: Decimal
    cantidad: int


class TicketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    codigo: str
    placa: str | None
    parking_lot_id: uuid.UUID
    vehicle_type_id: uuid.UUID
    entrada_at: datetime
    salida_at: datetime | None
    estado: EstadoTicket
    opcion_cobro: str | None
    observaciones: str | None


class TicketDetalleOut(TicketOut):
    # Solo en el detalle, no en los listados: es la llave del recibo del
    # cliente y no hace falta repartirla en cada búsqueda.
    token_publico: str
    codigo_verificacion: str
    items: list[ItemOut]
    anulacion_motivo: str | None
    plan_codigo: str | None = None
    plan_version: int | None = None


class PagoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    metodo: MetodoPago
    monto: Decimal
    subtotal: Decimal
    impuesto: Decimal
    recibido: Decimal | None
    cambio: Decimal | None
    referencia: str | None
    regla_aplicada: str | None = None
    monto_calculado: Decimal | None = None
    ajuste_manual: bool = False
    motivo_ajuste: str | None = None


class OpcionCobroOut(BaseModel):
    """Una forma de cobrarle a este ticket, ya cotizada."""

    codigo: str
    nombre: str
    recomendada: bool
    cotizacion: CotizacionOut


class CotizacionConOpcionesOut(CotizacionOut):
    """La cotización recomendada, más las alternativas.

    Los campos de la recomendada van en la raíz para que la vista en vivo
    —que solo necesita el valor que va corriendo— no tenga que saber nada
    de opciones.
    """

    opciones: list[OpcionCobroOut]


class ReciboOut(BaseModel):
    """Lo que ve el cliente al pagar y lo que se comparte por WhatsApp (D5)."""

    ticket: TicketOut
    cotizacion: CotizacionOut
    pago: PagoOut
    reintento: bool = False


class PlacaOcupadaOut(BaseModel):
    """Cuerpo del 409 cuando la placa ya tiene un ticket abierto (D6)."""

    detail: str
    ticket_abierto: TicketOut
