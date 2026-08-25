"""Bitácora de auditoría.

Guarda el email del actor además de su id: si el usuario se borra, el
registro sigue diciendo quién hizo qué.
"""

import uuid
from typing import Any

from sqlalchemy import ForeignKey, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, Timestamps, UUIDPk


class AuditLog(UUIDPk, Timestamps, Base):
    __tablename__ = "audit_log"

    # Nulo cuando la acción es de plataforma (crear un tenant, por ejemplo).
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("users.id", ondelete="SET NULL")
    )
    actor_email: Mapped[str | None] = mapped_column(String(320))

    accion: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    entidad: Mapped[str] = mapped_column(String(64), nullable=False)
    entidad_id: Mapped[str | None] = mapped_column(String(64))

    antes: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    despues: Mapped[dict[str, Any] | None] = mapped_column(JSONB)

    ip: Mapped[str | None] = mapped_column(String(45))
    user_agent: Mapped[str | None] = mapped_column(String(300))
