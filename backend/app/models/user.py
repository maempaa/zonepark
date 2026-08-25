"""Usuarios y su pertenencia a un tenant.

`users` es global a propósito: la misma persona puede administrar varios
parqueaderos de distintos clientes con una sola cuenta. Lo que sí es del
tenant es la *membresía*.
"""

import enum
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk, enum_column


class MembershipStatus(enum.StrEnum):
    ACTIVA = "activa"
    SUSPENDIDA = "suspendida"


class User(UUIDPk, Timestamps, Base):
    __tablename__ = "users"

    # Siempre en minúsculas: lo normaliza la capa de servicio.
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True, nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)

    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    telefono: Mapped[str | None] = mapped_column(String(32))

    # Administrador de la plataforma: crea tenants y queda fuera de RLS.
    # Todas sus acciones van al audit_log.
    is_platform_admin: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    # Bloqueo tras intentos fallidos.
    failed_attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    def __repr__(self) -> str:
        return f"<User {self.email}>"


class Membership(UUIDPk, TenantScoped, Timestamps, Base):
    """Un usuario dentro de un tenant. Los roles cuelgan de aquí, no del usuario."""

    __tablename__ = "memberships"
    __table_args__ = (
        UniqueConstraint("tenant_id", "user_id", name="uq_memberships_tenant_user"),
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )

    status: Mapped[MembershipStatus] = mapped_column(
        enum_column(MembershipStatus, 16),
        nullable=False,
        default=MembershipStatus.ACTIVA,
    )

    # PIN de 6 dígitos para el ingreso rápido del operario (D3).
    # Nulo mientras no lo configure.
    pin_hash: Mapped[str | None] = mapped_column(String(255))

    def __repr__(self) -> str:
        return f"<Membership {self.user_id} @ {self.tenant_id}>"
