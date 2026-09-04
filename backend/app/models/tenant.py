"""El tenant: un cliente de la plataforma."""

import enum

from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db.base import Base, Timestamps, UUIDPk, enum_column


class TenantStatus(enum.StrEnum):
    ACTIVO = "activo"
    SUSPENDIDO = "suspendido"


class Tenant(UUIDPk, Timestamps, Base):
    __tablename__ = "tenants"

    slug: Mapped[str] = mapped_column(String(63), unique=True, index=True, nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)

    # Campos fiscales: no se usan todavía (D4), pero existen desde el inicio
    # para que conectar facturación electrónica después no exija migrar datos.
    razon_social: Mapped[str | None] = mapped_column(String(200))
    nit: Mapped[str | None] = mapped_column(String(32))
    regimen_fiscal: Mapped[str | None] = mapped_column(String(64))

    # Valores por defecto del tenant; cada sede puede sobrescribir la zona horaria.
    timezone: Mapped[str] = mapped_column(
        String(64), nullable=False, default=settings.default_timezone
    )
    currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default=settings.default_currency
    )
    rounding_step: Mapped[int] = mapped_column(
        Integer, nullable=False, default=settings.default_rounding_step
    )

    # Vacío = la aplicación pone su texto por defecto. Se guarda solo
    # cuando el parqueadero escribe el suyo, para poder mejorar el de
    # fábrica sin pisarle el que ya redactó.
    aviso_responsabilidad: Mapped[str | None] = mapped_column(String(400))

    # El reglamento completo, el que va al pie del recibo en letra
    # pequeña. Vacío = el de fábrica.
    terminos_condiciones: Mapped[str | None] = mapped_column(Text)

    status: Mapped[TenantStatus] = mapped_column(
        enum_column(TenantStatus, 16),
        nullable=False,
        default=TenantStatus.ACTIVO,
    )

    def __repr__(self) -> str:
        return f"<Tenant {self.slug}>"
