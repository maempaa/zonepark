"""Turnos de caja y movimientos de efectivo.

El arqueo compara lo que la caja **debería** tener con lo que el operario
**cuenta** al cerrar. La diferencia es el dato que le importa al dueño.

Dos decisiones que hacen que ese número signifique algo:

* `esperado` se congela al cerrar el turno. Si se recalculara después,
  una anulación posterior o un cambio de tarifa cambiaría hacia atrás el
  arqueo de un turno ya cuadrado.
* Solo cuenta el efectivo. Una tarjeta no entra al cajón, así que
  incluirla en el esperado haría que todos los turnos aparecieran
  descuadrados.
"""

import enum
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Numeric, String, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk, enum_column


class EstadoTurno(enum.StrEnum):
    ABIERTO = "abierto"
    CERRADO = "cerrado"


class TipoMovimiento(enum.StrEnum):
    INGRESO = "ingreso"
    EGRESO = "egreso"


class CashShift(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "cash_shifts"
    __table_args__ = (
        # Índice parcial: un operario no puede tener dos turnos abiertos en
        # la misma sede. Se declara aquí además de crearse en la migración
        # para que el modelo y la base no diverjan.
        Index(
            "uq_turno_abierto_por_operario",
            "parking_lot_id",
            "membership_id",
            unique=True,
            postgresql_where=text("estado = 'abierto'"),
        ),
    )

    parking_lot_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parking_lots.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )
    membership_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memberships.id", ondelete="RESTRICT"),
        nullable=False, index=True,
    )

    abierto_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    cerrado_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    estado: Mapped[EstadoTurno] = mapped_column(
        enum_column(EstadoTurno, 16), nullable=False, default=EstadoTurno.ABIERTO, index=True
    )

    # Con cuánto arranca el cajón, para dar cambio.
    base_inicial: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    # Los tres se llenan al cerrar y ya no se recalculan.
    esperado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    contado: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    diferencia: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    notas_apertura: Mapped[str | None] = mapped_column(String(300))
    notas_cierre: Mapped[str | None] = mapped_column(String(300))

    movimientos: Mapped[list["CashMovement"]] = relationship(
        back_populates="turno", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<CashShift {self.id} {self.estado}>"


class CashMovement(UUIDPk, TenantScoped, Timestamps, Base):
    """Entradas y salidas de efectivo que no son cobros de tickets.

    Un cambio que se pide prestado, la compra de una escoba, el retiro que
    hace el dueño a mitad de turno. Sin esto, cualquier arqueo con esos
    movimientos aparecería descuadrado sin motivo.
    """

    __tablename__ = "cash_movements"

    cash_shift_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("cash_shifts.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    membership_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("memberships.id", ondelete="SET NULL")
    )

    tipo: Mapped[TipoMovimiento] = mapped_column(enum_column(TipoMovimiento, 16), nullable=False)
    concepto: Mapped[str] = mapped_column(String(160), nullable=False)
    monto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    turno: Mapped[CashShift] = relationship(back_populates="movimientos")

    @property
    def firmado(self) -> Decimal:
        """El monto con su signo: los egresos restan del cajón."""
        return self.monto if self.tipo is TipoMovimiento.INGRESO else -self.monto
