"""Roles y permisos, por tenant.

`permissions` es un catálogo fijo de la plataforma (no lo edita el cliente).
Los roles sí son de cada tenant: puede renombrarlos o crear los suyos.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk


class Permission(Timestamps, Base):
    """Catálogo global de permisos, con la forma `recurso:acción`."""

    __tablename__ = "permissions"

    codigo: Mapped[str] = mapped_column(String(64), primary_key=True)
    grupo: Mapped[str] = mapped_column(String(32), nullable=False)
    descripcion: Mapped[str] = mapped_column(String(200), nullable=False)

    def __repr__(self) -> str:
        return f"<Permission {self.codigo}>"


class Role(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "codigo", name="uq_roles_tenant_codigo"),)

    codigo: Mapped[str] = mapped_column(String(32), nullable=False)
    nombre: Mapped[str] = mapped_column(String(80), nullable=False)
    descripcion: Mapped[str | None] = mapped_column(String(200))

    # Los roles de sistema se siembran en cada tenant nuevo y no se borran.
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    def __repr__(self) -> str:
        return f"<Role {self.codigo}>"


class RolePermission(TenantScoped, Timestamps, Base):
    """Qué puede hacer un rol. Lleva tenant_id para que RLS también la cubra."""

    __tablename__ = "role_permissions"

    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), primary_key=True
    )
    permission_codigo: Mapped[str] = mapped_column(
        String(64), ForeignKey("permissions.codigo", ondelete="CASCADE"), primary_key=True
    )


class MembershipRole(UUIDPk, TenantScoped, Timestamps, Base):
    """Asigna un rol a una membresía, opcionalmente limitado a una sede.

    `parking_lot_id` nulo significa "todas las sedes del tenant".
    """

    __tablename__ = "membership_roles"
    __table_args__ = (
        # NULLS NOT DISTINCT (PG15+): sin esto, (m, r, NULL) podría insertarse
        # dos veces porque Postgres considera cada NULL distinto.
        Index(
            "uq_membership_roles_scope",
            "membership_id",
            "role_id",
            "parking_lot_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
    )

    membership_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("memberships.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("roles.id", ondelete="CASCADE"), nullable=False
    )
    parking_lot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("parking_lots.id", ondelete="CASCADE")
    )
