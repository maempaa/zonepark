"""Row Level Security: aislamiento entre tenants en la propia base.

La idea: la aplicación se conecta como dueño de las tablas, pero cada
transacción con datos de un tenant hace `SET LOCAL ROLE zonepark_app`.
Ese rol no es dueño de nada, así que **sí** queda sujeto a las políticas.
Las operaciones de sistema (login, administración de plataforma) se quedan
como dueño y las esquivan.

Las políticas se apoyan en `app.tenant_id`, que pone la sesión de la
aplicación con `SET LOCAL`. Si nadie lo pone, `current_setting(...,true)`
devuelve NULL, la comparación da NULL y **no se ve ninguna fila**: falla
cerrado, que es lo que queremos.

Revision ID: 0003_rls
Revises: 0002_plataforma
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0003_rls"
down_revision: str | None = "0002_plataforma"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

APP_ROLE = "zonepark_app"

# Expresión reutilizada: el tenant activo de esta transacción.
# NULLIF evita que un valor vacío reviente el cast a uuid.
TENANT_ACTUAL = "NULLIF(current_setting('app.tenant_id', true), '')::uuid"

# Tablas que llevan tenant_id y se filtran directo por él.
TABLAS_CON_TENANT = [
    "parking_lots",
    "memberships",
    "roles",
    "role_permissions",
    "membership_roles",
    "devices",
    "audit_log",
    "refresh_tokens",
]


def upgrade() -> None:
    # ── El rol de aplicación ────────────────────────────────────────────
    # NOLOGIN: no se conecta, solo se adopta con SET LOCAL ROLE.
    op.execute(f"""
        DO $$ BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = '{APP_ROLE}') THEN
                CREATE ROLE {APP_ROLE} NOLOGIN NOBYPASSRLS;
            END IF;
        END $$;
    """)
    # El dueño necesita ser miembro del rol para poder adoptarlo.
    op.execute(f"GRANT {APP_ROLE} TO CURRENT_USER;")
    op.execute(f"GRANT USAGE ON SCHEMA public TO {APP_ROLE};")
    op.execute(
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {APP_ROLE};"
    )
    op.execute(f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {APP_ROLE};")
    # Las tablas de las fases siguientes heredan los mismos permisos.
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {APP_ROLE};"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"GRANT USAGE, SELECT ON SEQUENCES TO {APP_ROLE};"
    )

    # alembic_version no le incumbe a la aplicación.
    op.execute(f"REVOKE ALL ON alembic_version FROM {APP_ROLE};")

    # `permissions` es un catálogo global de la plataforma: se lee, no se toca.
    op.execute(f"REVOKE INSERT, UPDATE, DELETE ON permissions FROM {APP_ROLE};")

    # ── Políticas de las tablas con tenant_id ───────────────────────────
    for tabla in TABLAS_CON_TENANT:
        op.execute(f"ALTER TABLE {tabla} ENABLE ROW LEVEL SECURITY;")
        op.execute(f"""
            CREATE POLICY {tabla}_aislamiento ON {tabla}
            FOR ALL
            USING (tenant_id = {TENANT_ACTUAL})
            WITH CHECK (tenant_id = {TENANT_ACTUAL});
        """)

    # ── tenants: cada uno se ve solo a sí mismo ─────────────────────────
    op.execute("ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY tenants_aislamiento ON tenants
        FOR ALL
        USING (id = {TENANT_ACTUAL})
        WITH CHECK (id = {TENANT_ACTUAL});
    """)

    # ── users: tabla global, se filtra por membresía ────────────────────
    # Un tenant solo ve a las personas que son miembros suyos.
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY;")
    op.execute(f"""
        CREATE POLICY users_por_membresia ON users
        FOR ALL
        USING (
            EXISTS (
                SELECT 1 FROM memberships m
                WHERE m.user_id = users.id
                  AND m.tenant_id = {TENANT_ACTUAL}
            )
        )
        -- Al crear un usuario todavía no existe la membresía, así que el
        -- INSERT se permite; lo que no se permite nunca desde una sesión
        -- de tenant es fabricar un administrador de plataforma.
        WITH CHECK (NOT is_platform_admin);
    """)


def downgrade() -> None:
    for tabla in [*TABLAS_CON_TENANT, "tenants"]:
        op.execute(f"DROP POLICY IF EXISTS {tabla}_aislamiento ON {tabla};")
        op.execute(f"ALTER TABLE {tabla} DISABLE ROW LEVEL SECURITY;")
    op.execute("DROP POLICY IF EXISTS users_por_membresia ON users;")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY;")
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE SELECT, INSERT, UPDATE, DELETE ON TABLES FROM {APP_ROLE};"
    )
    op.execute(
        "ALTER DEFAULT PRIVILEGES IN SCHEMA public "
        f"REVOKE USAGE, SELECT ON SEQUENCES FROM {APP_ROLE};"
    )
    op.execute(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {APP_ROLE};")
    op.execute(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {APP_ROLE};")
    op.execute(f"REVOKE USAGE ON SCHEMA public FROM {APP_ROLE};")
    # El rol no se borra: puede estar compartido con otras bases del clúster.
