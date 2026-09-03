"""Teléfono del cliente, recordado por placa.

El recibo se manda por WhatsApp, y pedir el número en cada visita a quien
parquea todos los días es fricción pura en la caseta. Se guarda una sola
vez por placa y las siguientes ya viene puesto.

Es un dato personal: existe para mandarle a esa persona el recibo de su
vehículo y para nada más. Se guarda el último número que se usó, no un
historial, y se pisa cuando cambia.

Revision ID: 0011_contactos
Revises: 0010_opcion_en_ingreso
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_contactos"
down_revision: str | None = "0010_opcion_en_ingreso"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TENANT_ACTUAL = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "plate_contacts",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("placa", sa.String(length=16), nullable=False),
        sa.Column("telefono", sa.String(length=24), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True),
            server_default=sa.text("now()"), nullable=False,
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        # Una placa, un número. Buscar por placa es la única consulta que
        # hace esta tabla, y pasa en la pantalla que más se usa.
        sa.UniqueConstraint("tenant_id", "placa", name="uq_plate_contacts_tenant_placa"),
    )

    op.execute("ALTER TABLE plate_contacts ENABLE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY plate_contacts_aislamiento ON plate_contacts
        FOR ALL
        USING (tenant_id = {TENANT_ACTUAL})
        WITH CHECK (tenant_id = {TENANT_ACTUAL});
    """)


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS plate_contacts_aislamiento ON plate_contacts;")
    op.execute("ALTER TABLE plate_contacts DISABLE ROW LEVEL SECURITY;")
    op.drop_table("plate_contacts")
