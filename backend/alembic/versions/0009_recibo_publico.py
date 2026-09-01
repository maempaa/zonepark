"""Recibo en vivo para el cliente.

Quien deja el carro no tiene forma de saber cuánto lleva corriendo hasta
que vuelve por él. Esta migración abre esa puerta con tres piezas.

`tickets.token_publico` es la llave: un secreto por ticket, porque el
consecutivo (S1-000002) es adivinable y la placa está a la vista en el
parabrisas. Sin él, cualquiera vería el recibo ajeno probando números.

`parking_lots.telefono` y `tenants.aviso_responsabilidad` son lo que el
cliente necesita ver junto al monto: a quién llamar, y que el parqueadero
no responde por objetos dejados dentro del vehículo. El aviso queda vacío
y la aplicación pone un texto por defecto, para poder mejorarlo en un
lugar sin migrar los que ya escribieron el suyo.

Revision ID: 0009_recibo_publico
Revises: 0008_opcion_activa
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009_recibo_publico"
down_revision: str | None = "0008_opcion_activa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("parking_lots", sa.Column("telefono", sa.String(length=32), nullable=True))
    op.add_column(
        "tenants", sa.Column("aviso_responsabilidad", sa.String(length=400), nullable=True)
    )

    # Se agrega opcional, se llena, y recién entonces se exige. Los tickets
    # abiertos hoy tienen que poder mostrar su recibo igual que los nuevos.
    op.add_column("tickets", sa.Column("token_publico", sa.String(length=32), nullable=True))
    op.execute("UPDATE tickets SET token_publico = replace(gen_random_uuid()::text, '-', '')")
    op.alter_column("tickets", "token_publico", nullable=False)
    op.create_index(
        "ix_tickets_token_publico", "tickets", ["token_publico"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_tickets_token_publico", table_name="tickets")
    op.drop_column("tickets", "token_publico")
    op.drop_column("tenants", "aviso_responsabilidad")
    op.drop_column("parking_lots", "telefono")
