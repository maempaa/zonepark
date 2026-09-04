"""El recibo también se manda por correo.

La misma idea del teléfono: se pregunta una vez por placa y las
siguientes ya viene puesto. Un cliente puede dar el correo, el WhatsApp,
o los dos, así que el teléfono deja de ser obligatorio: exigirlo para
guardar un correo obligaría a inventárselo.

Revision ID: 0014_correo_contacto
Revises: 0013_codigo_verificacion
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_correo_contacto"
down_revision: str | None = "0013_codigo_verificacion"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("plate_contacts", sa.Column("correo", sa.String(length=160), nullable=True))
    op.alter_column("plate_contacts", "telefono", existing_type=sa.String(24), nullable=True)


def downgrade() -> None:
    # Las filas que solo tienen correo no pueden volver: sin teléfono no
    # caben en el esquema anterior.
    op.execute("DELETE FROM plate_contacts WHERE telefono IS NULL")
    op.alter_column("plate_contacts", "telefono", existing_type=sa.String(24), nullable=False)
    op.drop_column("plate_contacts", "correo")
