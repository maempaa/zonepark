"""Términos y condiciones del recibo.

El aviso de objetos perdidos ya existía y es corto: va destacado, para que
se lea. Los términos son otra cosa —el reglamento completo del
parqueadero— y van al pie, en letra pequeña, como en el recibo de papel.

Se guarda vacío y la aplicación pone su texto por defecto, igual que el
aviso: así se puede mejorar el de fábrica sin pisarle el suyo a quien ya
redactó el propio.

Revision ID: 0012_terminos
Revises: 0011_contactos
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0012_terminos"
down_revision: str | None = "0011_contactos"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenants", sa.Column("terminos_condiciones", sa.Text(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("tenants", "terminos_condiciones")
