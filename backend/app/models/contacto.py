"""A qué número se le manda el recibo de cada placa."""

from sqlalchemy import String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base, TenantScoped, Timestamps, UUIDPk


class PlateContact(UUIDPk, TenantScoped, Timestamps, Base):
    __tablename__ = "plate_contacts"
    __table_args__ = (
        UniqueConstraint("tenant_id", "placa", name="uq_plate_contacts_tenant_placa"),
    )

    # Normalizada como en los tickets: sin guiones ni espacios, en mayúscula.
    placa: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # Como lo tecleó el operario. Convertirlo al formato de WhatsApp es
    # cosa de quien arma el enlace, no de lo que se guarda: así el número
    # se sigue leyendo igual que en la agenda de quien lo dictó.
    telefono: Mapped[str] = mapped_column(String(24), nullable=False)

    def __repr__(self) -> str:
        return f"<PlateContact {self.placa}>"
