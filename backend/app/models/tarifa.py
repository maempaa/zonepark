"""Planes tarifarios: lo que convierte tiempo en dinero.

Un plan agrupa reglas. Cada regla dice cómo se cobra **un tipo de vehículo**
en **una franja horaria**. Un mismo tipo puede tener varias reglas —diurna,
nocturna, fin de semana— y el motor elige la que corresponde a cada tramo.

Estas tablas son el origen del `ReglaTarifaria` que consume el motor. La
conversión vive en `app/domain/pricing/snapshot.py`, y su resultado es lo
que se congela en el ticket al abrirlo.
"""

import enum
import uuid
from datetime import date, time
from decimal import Decimal

from sqlalchemy import (
    ARRAY,
    Boolean,
    Date,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Time,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk, enum_column
from app.domain.pricing.modelos import (
    ModoCobro,
    ModoImpuesto,
    ModoRedondeo,
    UnidadEscalon,
)


class EstadoPlan(enum.StrEnum):
    BORRADOR = "borrador"
    ACTIVO = "activo"
    ARCHIVADO = "archivado"


class RatePlan(UUIDPk, TenantScoped, Timestamps, Base):
    """Un conjunto de tarifas con vigencia.

    Los planes no se editan una vez activos: se archivan y se publica una
    versión nueva. Así un ticket abierto hace tres días siempre puede
    señalar la versión exacta con la que se le cotizó.
    """

    __tablename__ = "rate_plans"
    __table_args__ = (
        UniqueConstraint("tenant_id", "codigo", "version", name="uq_rate_plans_codigo_version"),
    )

    codigo: Mapped[str] = mapped_column(String(32), nullable=False)
    nombre: Mapped[str] = mapped_column(String(120), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # Nulo = aplica a todas las sedes del tenant.
    parking_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parking_lots.id", ondelete="CASCADE"), index=True
    )

    estado: Mapped[EstadoPlan] = mapped_column(
        enum_column(EstadoPlan, 16), nullable=False, default=EstadoPlan.BORRADOR
    )
    vigente_desde: Mapped[date | None] = mapped_column(Date)
    vigente_hasta: Mapped[date | None] = mapped_column(Date)

    reglas: Mapped[list["RateRule"]] = relationship(
        back_populates="plan", cascade="all, delete-orphan", lazy="selectin"
    )

    def __repr__(self) -> str:
        return f"<RatePlan {self.codigo} v{self.version} {self.estado}>"


class RateRule(UUIDPk, TenantScoped, Timestamps, Base):
    """Cómo se cobra un tipo de vehículo dentro de un plan."""

    __tablename__ = "rate_rules"
    __table_args__ = (
        UniqueConstraint("rate_plan_id", "codigo", name="uq_rate_rules_plan_codigo"),
    )

    rate_plan_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rate_plans.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )
    vehicle_type_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("vehicle_types.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    # Identifica la regla en el desglose que ve el operario.
    codigo: Mapped[str] = mapped_column(String(48), nullable=False)

    modo: Mapped[ModoCobro] = mapped_column(enum_column(ModoCobro, 32), nullable=False)

    precio_minuto: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    precio_bloque: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    precio_plena: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)
    precio_dia: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False, default=0)

    # El campo que convierte "hora o fracción" en "media hora o fracción".
    bloque_minutos: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    dia_horas: Mapped[int] = mapped_column(Integer, nullable=False, default=24)

    # Modificadores
    gracia_minutos: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    cobro_minimo: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tope_diario: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))
    tarifa_ticket_perdido: Mapped[Decimal | None] = mapped_column(Numeric(14, 2))

    redondeo_modo: Mapped[ModoRedondeo] = mapped_column(
        enum_column(ModoRedondeo, 16), nullable=False, default=ModoRedondeo.CERCANO
    )
    redondeo_paso: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    impuesto_modo: Mapped[ModoImpuesto] = mapped_column(
        enum_column(ModoImpuesto, 16), nullable=False, default=ModoImpuesto.INCLUIDO
    )
    impuesto_tasa: Mapped[Decimal] = mapped_column(Numeric(5, 4), nullable=False, default=0)

    # ── Franja de aplicación ────────────────────────────────────────────
    # Sin franja, la regla es la base del plan y aplica siempre.
    tiene_franja: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 0 = lunes … 6 = domingo, igual que Python.
    franja_dias: Mapped[list[int] | None] = mapped_column(ARRAY(SmallInteger))
    franja_desde: Mapped[time | None] = mapped_column(Time)
    franja_hasta: Mapped[time | None] = mapped_column(Time)
    franja_incluye_festivos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    franja_solo_festivos: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    prioridad: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    plan: Mapped[RatePlan] = relationship(back_populates="reglas")
    escalones: Mapped[list["RateTier"]] = relationship(
        back_populates="regla",
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="RateTier.desde_minuto",
    )

    def __repr__(self) -> str:
        return f"<RateRule {self.codigo} {self.modo}>"


class RateTier(UUIDPk, TenantScoped, Timestamps, Base):
    """Un tramo de la tarifa escalonada, medido desde la entrada."""

    __tablename__ = "rate_tiers"
    __table_args__ = (
        UniqueConstraint("rate_rule_id", "desde_minuto", name="uq_rate_tiers_regla_desde"),
    )

    rate_rule_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("rate_rules.id", ondelete="CASCADE"),
        nullable=False, index=True,
    )

    desde_minuto: Mapped[int] = mapped_column(Integer, nullable=False)
    hasta_minuto: Mapped[int | None] = mapped_column(Integer)  # nulo = sin límite
    precio: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    unidad: Mapped[UnidadEscalon] = mapped_column(
        enum_column(UnidadEscalon, 16), nullable=False, default=UnidadEscalon.BLOQUE
    )
    bloque_minutos: Mapped[int] = mapped_column(Integer, nullable=False, default=60)

    regla: Mapped[RateRule] = relationship(back_populates="escalones")
