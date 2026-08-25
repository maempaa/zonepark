"""Dispositivos registrados para el ingreso rápido con PIN (D3).

Un dispositivo pertenece a una membresía. El administrador puede revocarlo
en remoto: es lo que hace utilizable el PIN en el celular propio del operario.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk


class Device(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "devices"
    __table_args__ = (
        UniqueConstraint("tenant_id", "fingerprint", name="uq_devices_tenant_fingerprint"),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # Sede donde vive el dispositivo. Nulo si es el celular del operario.
    parking_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parking_lots.id", ondelete="SET NULL")
    )

    # Identificador estable que genera el navegador y guarda en la cookie.
    fingerprint: Mapped[str] = mapped_column(String(128), nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    user_agent: Mapped[str | None] = mapped_column(String(300))

    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None

    def __repr__(self) -> str:
        return f"<Device {self.nombre}>"
