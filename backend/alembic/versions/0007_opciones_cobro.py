"""Opciones de cobro y ajuste manual del monto.

Un parqueadero no cobra siempre igual: al mismo carro se le puede aplicar
la tarifa por hora, una plena de todo el día o un convenio. Quien cobra
elige en el momento, y a veces pone un valor a mano.

Para que eso sea auditable hace falta guardar tres cosas que antes no se
guardaban: con qué opción se calculó, cuánto había calculado el sistema, y
si el monto final se puso a mano y por qué. Sin `monto_calculado`, un
ajuste manual sería indistinguible de un cobro normal.

Revision ID: 0007_opciones_cobro
Revises: 0006_caja
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007_opciones_cobro"
down_revision: str | None = "0006_caja"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Cómo se llama la opción de cara a quien cobra. Nulo = se deduce del
    # modo, para no obligar a renombrar las tarifas que ya existen.
    op.add_column("rate_rules", sa.Column("nombre", sa.String(length=80), nullable=True))

    op.add_column("payments", sa.Column("regla_aplicada", sa.String(length=48), nullable=True))
    op.add_column("payments", sa.Column("monto_calculado", sa.Numeric(14, 2), nullable=True))
    # server_default porque ya hay pagos: los anteriores no fueron manuales.
    op.add_column(
        "payments",
        sa.Column("ajuste_manual", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.alter_column("payments", "ajuste_manual", server_default=None)
    op.add_column("payments", sa.Column("motivo_ajuste", sa.String(length=300), nullable=True))


def downgrade() -> None:
    op.drop_column("payments", "motivo_ajuste")
    op.drop_column("payments", "ajuste_manual")
    op.drop_column("payments", "monto_calculado")
    op.drop_column("payments", "regla_aplicada")
    op.drop_column("rate_rules", "nombre")
