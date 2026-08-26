"""Catálogos parametrizables por tenant.

Tipos de vehículo y artículos son **tablas**, no enums: cada parqueadero
define los suyos. Uno cobra carro, moto y bicicleta; otro añade patineta
y camioneta. Nada de esto debería exigir un despliegue.
"""

from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, Integer, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk


class VehicleType(UUIDPk, TenantScoped, Timestamps, Base):
    """Un tipo de vehículo o artículo que ocupa espacio y se cobra por tiempo."""

    __tablename__ = "vehicle_types"
    __table_args__ = (
        UniqueConstraint("tenant_id", "codigo", name="uq_vehicle_types_tenant_codigo"),
    )

    codigo: Mapped[str] = mapped_column(String(32), nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    # Nombre de icono que pinta el frontend; sin ruta ni extensión.
    icono: Mapped[str | None] = mapped_column(String(40))

    # Una bicicleta o un casco no tienen placa.
    requiere_placa: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Expresión regular opcional para validar la placa al registrar el ingreso.
    patron_placa: Mapped[str | None] = mapped_column(String(120))

    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<VehicleType {self.codigo}>"


class ServiceItem(UUIDPk, TenantScoped, Timestamps, Base):
    """Algo que se cobra aparte del tiempo: casco, lavada, ticket perdido."""

    __tablename__ = "service_items"
    __table_args__ = (
        UniqueConstraint("tenant_id", "codigo", name="uq_service_items_tenant_codigo"),
    )

    codigo: Mapped[str] = mapped_column(String(32), nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    precio: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    activo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    orden: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<ServiceItem {self.codigo}>"


class Holiday(UUIDPk, TenantScoped, Timestamps, Base):
    """Calendario de festivos del tenant, para las tarifas de día festivo."""

    __tablename__ = "holidays"
    __table_args__ = (UniqueConstraint("tenant_id", "fecha", name="uq_holidays_tenant_fecha"),)

    fecha: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
