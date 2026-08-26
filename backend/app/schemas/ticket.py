"""Esquemas de la operación."""

import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.ticket import EstadoTicket, MetodoPago
from app.schemas.tarifa import CotizacionOut


class IngresoIn(BaseModel):
    parking_lot_id: uuid.UUID
    vehicle_type_id: uuid.UUID
    placa: str | None = Field(default=None, max_length=16)
    observaciones: str | None = Field(default=None, max_length=300)
    # D6: el operario confirma que de verdad son dos ingresos distintos.
    forzar: bool = False


class ItemIn(BaseModel):
    codigo: str
    cantidad: int = Field(default=1, ge=1, le=99)


class CobroIn(BaseModel):
    metodo: MetodoPago = MetodoPago.EFECTIVO
    # Solo en efectivo: lo que entrega el cliente, para calcular el cambio.
    recibido: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    referencia: str | None = Field(default=None, max_length=64)


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
    observaciones: str | None


class TicketDetalleOut(TicketOut):
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
