"""Tickets, cargos y pagos.

El ticket es el documento de la operación: se abre cuando entra el
vehículo y se cierra cuando paga. Entre esos dos momentos pueden pasar
días, y en ese lapso el parqueadero puede haber subido las tarifas o
cambiado el precio de un casco.

Por eso aquí se congelan **dos** cosas, no una:

* `rate_snapshot` — las reglas tarifarias vigentes al entrar.
* el precio de cada artículo en su propia línea, cuando se añade.

Sin lo segundo, subir el precio del casco recalcularía hacia atrás los
cascos ya entregados.

Al cerrar se guarda además el desglose completo en `charges`. Es
redundante con lo que sabría recalcular el motor, y es a propósito: el
recibo que se le dio al cliente tiene que poder reproducirse tal cual,
aunque años después cambie hasta la forma de redondear.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk, enum_column


class EstadoTicket(enum.StrEnum):
    ABIERTO = "abierto"
    CERRADO = "cerrado"
    ANULADO = "anulado"


class MetodoPago(enum.StrEnum):
    EFECTIVO = "efectivo"
    TARJETA = "tarjeta"
    QR = "qr"
    TRANSFERENCIA = "transferencia"
    CORTESIA = "cortesia"


class Ticket(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "tickets"
    __table_args__ = (
        UniqueConstraint("parking_lot_id", "numero", name="uq_tickets_sede_numero"),
        # La búsqueda del operario es por placa dentro de los abiertos de su sede.
        Index("ix_tickets_busqueda", "parking_lot_id", "estado", "placa"),
    )

    parking_lot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parking_lots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    vehicle_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicle_types.id", ondelete="RESTRICT"),
        nullable=False,
    )

    # Consecutivo por sede, y su forma legible: S1-000042.
    numero: Mapped[int] = mapped_column(Integer, nullable=False)
    codigo: Mapped[str] = mapped_column(String(24), nullable=False, index=True)

    # Nula para los tipos que no llevan placa (bicicleta, casco).
    placa: Mapped[str | None] = mapped_column(String(16), index=True)

    entrada_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    salida_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    estado: Mapped[EstadoTicket] = mapped_column(
        enum_column(EstadoTicket, 16), nullable=False, default=EstadoTicket.ABIERTO, index=True
    )

    operario_entrada_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )
    operario_salida_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )

    # Las reglas tarifarias congeladas al abrir. Ver el docstring del módulo.
    rate_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)

    observaciones: Mapped[str | None] = mapped_column(String(300))
    anulacion_motivo: Mapped[str | None] = mapped_column(String(300))

    items: Mapped[list["TicketItem"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", lazy="selectin"
    )
    cargos: Mapped[list["Charge"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan",
        lazy="selectin", order_by="Charge.orden",
    )
    pagos: Mapped[list["Payment"]] = relationship(
        back_populates="ticket", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<Ticket {self.codigo} {self.estado}>"


class TicketItem(UUIDPk, TenantScoped, Timestamps, Base):
    """Un artículo añadido al ticket, con su precio congelado."""

    __tablename__ = "ticket_items"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    # Referencia suelta: si el artículo se borra del catálogo, la línea del
    # ticket sobrevive con su nombre y su precio.
    service_item_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("service_items.id", ondelete="SET NULL")
    )
    codigo: Mapped[str] = mapped_column(String(32), nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    precio_unitario: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    cantidad: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    ticket: Mapped[Ticket] = relationship(back_populates="items")

    @property
    def total(self) -> Decimal:
        return self.precio_unitario * self.cantidad


class Charge(UUIDPk, TenantScoped, Timestamps, Base):
    """Una línea del recibo, tal como se le mostró al cliente."""

    __tablename__ = "charges"

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    concepto: Mapped[str] = mapped_column(String(120), nullable=False)
    detalle: Mapped[str | None] = mapped_column(String(120))
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    ticket: Mapped[Ticket] = relationship(back_populates="cargos")


class Payment(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "payments"
    __table_args__ = (
        # Reintentar un cobro con la misma llave no cobra dos veces.
        UniqueConstraint("tenant_id", "idempotency_key", name="uq_payments_idempotency"),
    )

    ticket_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tickets.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    metodo: Mapped[MetodoPago] = mapped_column(enum_column(MetodoPago, 16), nullable=False)

    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    impuesto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    # Solo en efectivo: lo que entregó el cliente y el cambio devuelto.
    recibido: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    cambio: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    referencia: Mapped[str | None] = mapped_column(String(64))
    idempotency_key: Mapped[str | None] = mapped_column(String(64))

    # El turno de caja llega en la fase 4.
    cash_shift_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True))

    ticket: Mapped[Ticket] = relationship(back_populates="pagos")
