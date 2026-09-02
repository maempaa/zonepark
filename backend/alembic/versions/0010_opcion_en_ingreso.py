"""La forma de cobro se elige al entrar, no al salir.

Hasta ahora quien cobraba decidía en la salida con qué tarifa se liquidaba.
El cliente pidió lo contrario: que se acuerde al recibir el vehículo, para
que quien lo deja sepa desde el primer minuto bajo qué tarifa está y lo vea
en su recibo.

`opcion_cobro` guarda el código de la regla acordada. Nulo significa
"la que aplique automáticamente", que es como se comportaban todos los
tickets hasta hoy: por eso se agrega opcional y no se rellena. Además es
lo que hay que dejar en los parqueaderos con tarifa nocturna o de festivo,
porque esas franjas solo entran por la vía automática.

Revision ID: 0010_opcion_en_ingreso
Revises: 0009_recibo_publico
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_opcion_en_ingreso"
down_revision: str | None = "0009_recibo_publico"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Mismo largo que payments.regla_aplicada: guardan el mismo código.
    op.add_column("tickets", sa.Column("opcion_cobro", sa.String(length=48), nullable=True))


def downgrade() -> None:
    op.drop_column("tickets", "opcion_cobro")
