"""Base de los modelos y mixins comunes.

Todos los modelos deben importarse al final de este archivo para que
Alembic los vea al autogenerar migraciones.
"""

import enum as _enum
import uuid
from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, func, text
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import DeclarativeBase, Mapped, declared_attr, mapped_column


class Base(DeclarativeBase):
    pass


def enum_column(enum_cls: type[_enum.Enum], length: int) -> Enum:
    """VARCHAR + CHECK en vez de un tipo ENUM nativo de Postgres.

    Los ENUM nativos son incómodos de alterar en una migración; un VARCHAR
    con CHECK se cambia con un ALTER simple. `create_constraint=True` es
    obligatorio: desde SQLAlchemy 1.4 el valor por defecto es False, y sin
    él la columna acepta cualquier cadena.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        create_constraint=True,
        values_callable=lambda e: [m.value for m in e],
    )


class UUIDPk:
    """Clave primaria UUID generada por la base."""

    id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


class Timestamps:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class TenantScoped:
    """Marca una tabla como propiedad de un tenant.

    La columna `tenant_id` es lo que leen las políticas RLS. Ninguna consulta
    de la aplicación la filtra a mano: la pone el contexto de la petición.
    """

    @declared_attr
    def tenant_id(cls) -> Mapped[uuid.UUID]:  # noqa: N805
        return mapped_column(
            PGUUID(as_uuid=True),
            ForeignKey("tenants.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )


# Importar al final: registra los modelos en Base.metadata para Alembic.
from app.models import (  # noqa: E402,F401
    audit,
    caja,
    catalogo,
    contacto,
    device,
    parking_lot,
    rbac,
    tarifa,
    tenant,
    ticket,
    token,
    user,
)
