"""Sedes (parqueaderos) de un tenant."""

import enum

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk, enum_column


class DevicePolicy(enum.StrEnum):
    """D3: cada sede decide cómo entra el operario.

    PIN_PERSISTENTE  — dispositivo de la empresa en la caseta; el PIN vale
                       durante semanas sobre un dispositivo registrado.
    LOGIN_POR_TURNO  — celular propio del operario; sesión corta y cierre
                       al terminar el turno.
    """

    PIN_PERSISTENTE = "pin_persistente"
    LOGIN_POR_TURNO = "login_por_turno"


class ParkingLot(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "parking_lots"
    __table_args__ = (
        UniqueConstraint("tenant_id", "codigo", name="uq_parking_lots_tenant_codigo"),
    )

    codigo: Mapped[str] = mapped_column(String(32), nullable=False)
    nombre: Mapped[str] = mapped_column(String(160), nullable=False)
    direccion: Mapped[str | None] = mapped_column(String(240))
    # Lo ve el cliente en su recibo: a quién llamar si algo pasa.
    telefono: Mapped[str | None] = mapped_column(String(32))

    # Nulo = hereda la del tenant. La aritmética de tarifas usa la de la sede.
    timezone: Mapped[str | None] = mapped_column(String(64))

    device_policy: Mapped[DevicePolicy] = mapped_column(
        enum_column(DevicePolicy, 24),
        nullable=False,
        default=DevicePolicy.PIN_PERSISTENTE,
    )

    # Prefijo del consecutivo de tickets de esta sede: S1-000042.
    ticket_prefix: Mapped[str] = mapped_column(String(8), nullable=False, default="T")
    # Último número entregado. Se incrementa con un UPDATE ... RETURNING, que
    # bloquea la fila: dos ingresos simultáneos no pueden repetir consecutivo.
    ultimo_consecutivo: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    def __repr__(self) -> str:
        return f"<ParkingLot {self.codigo}>"
