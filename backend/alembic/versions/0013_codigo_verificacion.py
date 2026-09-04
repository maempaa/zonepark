"""Código de verificación para entregar el vehículo.

Cinco dígitos por ticket. El cliente los ve en su recibo y quien entrega
los ve en la pantalla de cobro: si no coinciden, el carro no sale.

Es la contraseña del ticket de papel de toda la vida, y como aquella vale
por sí sola: no se deriva del consecutivo ni de la placa, que están a la
vista de cualquiera. Se sortea entre 10000 y 99999 para que siempre se
lea de cinco cifras; quien lo dicta por teléfono no tiene que explicar
ceros de más al principio.

Revision ID: 0013_codigo_verificacion
Revises: 0012_terminos
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0013_codigo_verificacion"
down_revision: str | None = "0012_terminos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tickets", sa.Column("codigo_verificacion", sa.String(length=5), nullable=True)
    )
    # Los tickets abiertos de hoy también tienen que poder entregarse.
    op.execute(
        "UPDATE tickets SET codigo_verificacion = "
        "(floor(random() * 90000) + 10000)::int::text"
    )
    op.alter_column("tickets", "codigo_verificacion", nullable=False)


def downgrade() -> None:
    op.drop_column("tickets", "codigo_verificacion")
