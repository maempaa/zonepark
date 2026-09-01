"""Encender y apagar cada opción de cobro.

Un parqueadero define varias formas de cobrar el mismo vehículo —por hora,
por fracción, plena— y no siempre las ofrece todas. Apagar una tenía que
borrarla, y con ella su precio; ahora se apaga y el precio se conserva
para recuperarla sin volver a teclearla.

Revision ID: 0008_opcion_activa
Revises: 0007_opciones_cobro
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0008_opcion_activa"
down_revision: str | None = "0007_opciones_cobro"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Las tarifas que ya existen estaban todas en uso.
    op.add_column(
        "rate_rules",
        sa.Column("activa", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.alter_column("rate_rules", "activa", server_default=None)


def downgrade() -> None:
    op.drop_column("rate_rules", "activa")
