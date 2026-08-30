"""Panel de plataforma.

Estas rutas corren por encima de RLS, así que lo que más importa probar es
quién puede llegar a ellas: un token de tenant no debe servir, y quitarle
la marca a alguien tiene que surtir efecto sin esperar a que su token
caduque.
"""

import uuid

import pytest
from sqlalchemy import select

from app.db.session import system_scope, tenant_scope
from app.models.tenant import Tenant, TenantStatus
from app.models.user import User
from app.services.plataforma import crear_admin_de_plataforma

from .conftest import CLAVE, cabecera, entrar

CLAVE_LARGA = "plataforma12345"


@pytest.fixture
async def superadmin():
    """Un administrador de plataforma con correo único por prueba."""
    email = f"super-{uuid.uuid4().hex[:8]}@plataforma.com.co"
    async with system_scope() as session:
        await crear_admin_de_plataforma(
            session, email=email, nombre="Superadmin", password=CLAVE_LARGA
        )
    yield email
    async with system_scope() as session:
        user = await session.scalar(select(User).where(User.email == email))
        if user:
            await session.delete(user)


async def _entrar_plataforma(client, email: str) -> dict[str, str]:
    r = await client.post(
        "/api/v1/admin/auth/login", json={"email": email, "password": CLAVE_LARGA}
    )
    assert r.status_code == 200, r.text
    return cabecera(r.json()["access_token"])


# ── Acceso ───────────────────────────────────────────────────────────────

async def test_el_superadmin_entra(superadmin, client):
    cab = await _entrar_plataforma(client, superadmin)
    r = await client.get("/api/v1/admin/me", headers=cab)
    assert r.status_code == 200
    assert r.json()["email"] == superadmin


async def test_un_usuario_normal_no_entra_a_la_plataforma(dos_tenants, client):
    """Mismo mensaje que una clave mala: no se revela quién es administrador."""
    a, _ = dos_tenants
    r = await client.post(
        "/api/v1/admin/auth/login", json={"email": a.admin, "password": CLAVE}
    )
    assert r.status_code == 401


async def test_un_token_de_tenant_no_sirve_en_la_plataforma(dos_tenants, client):
    a, _ = dos_tenants
    token = await entrar(client, a.slug, a.admin)
    r = await client.get("/api/v1/admin/tenants", headers=cabecera(token))
    assert r.status_code == 403
    assert "no administra la plataforma" in r.json()["detail"]


async def test_sin_token_no_se_entra(client):
    assert (await client.get("/api/v1/admin/tenants")).status_code == 401


async def test_quitar_la_marca_surte_efecto_sin_esperar_al_token(superadmin, client):
    """El token dura quince minutos; ver los datos de todos los clientes
    quince minutos de más no es aceptable, así que la marca se comprueba
    contra la base en cada petición."""
    cab = await _entrar_plataforma(client, superadmin)
    assert (await client.get("/api/v1/admin/tenants", headers=cab)).status_code == 200

    async with system_scope() as session:
        user = await session.scalar(select(User).where(User.email == superadmin))
        user.is_platform_admin = False

    # Mismo token, ya sin privilegio.
    r = await client.get("/api/v1/admin/tenants", headers=cab)
    assert r.status_code == 403


# ── Clientes ─────────────────────────────────────────────────────────────

def _cliente(slug: str) -> dict:
    return {
        "slug": slug,
        "nombre": "Parqueadero de prueba",
        "sede_codigo": "S1",
        "sede_nombre": "Sede principal",
        "admin_email": f"admin-{slug}@prueba.com.co",
        "admin_nombre": "Administrador",
        "admin_password": "contrasenalarga1",
    }


async def test_crear_un_cliente_lo_deja_listo_para_operar(superadmin, client):
    """Un tenant sin roles, sin sede y sin nadie que entre no sirve de nada."""
    cab = await _entrar_plataforma(client, superadmin)
    slug = f"nuevo-{uuid.uuid4().hex[:8]}"

    r = await client.post("/api/v1/admin/tenants", headers=cab, json=_cliente(slug))
    assert r.status_code == 201
    creado = r.json()

    # El administrador puede entrar de inmediato y tiene todos los permisos.
    token = await entrar(client, slug, f"admin-{slug}@prueba.com.co", "contrasenalarga1")
    perfil = (await client.get(f"/api/v1/t/{slug}/auth/me", headers=cabecera(token))).json()
    assert perfil["roles"] == ["tenant_admin"]
    assert len(perfil["permisos"]) == 22

    # Y tiene sede desde el primer momento.
    sedes = (await client.get(f"/api/v1/t/{slug}/sedes", headers=cabecera(token))).json()
    assert [s["codigo"] for s in sedes] == ["S1"]

    async with system_scope() as session:
        await session.delete(await session.get(Tenant, uuid.UUID(creado["id"])))
        u = await session.scalar(
            select(User).where(User.email == f"admin-{slug}@prueba.com.co")
        )
        if u:
            await session.delete(u)


async def test_no_se_repite_el_identificador(superadmin, dos_tenants, client):
    a, _ = dos_tenants
    cab = await _entrar_plataforma(client, superadmin)
    r = await client.post("/api/v1/admin/tenants", headers=cab, json=_cliente(a.slug))
    assert r.status_code == 409


@pytest.mark.parametrize("slug", ["admin", "api", "t", "login"])
async def test_los_identificadores_reservados_se_rechazan(superadmin, client, slug):
    """Chocarían con rutas del propio sistema."""
    cab = await _entrar_plataforma(client, superadmin)
    r = await client.post("/api/v1/admin/tenants", headers=cab, json=_cliente(slug))
    assert r.status_code == 422


async def test_la_clave_del_administrador_tiene_minimo(superadmin, client):
    """Es la cuenta que cambia tarifas y ve la caja."""
    cab = await _entrar_plataforma(client, superadmin)
    datos = _cliente(f"corta-{uuid.uuid4().hex[:8]}") | {"admin_password": "corta"}
    r = await client.post("/api/v1/admin/tenants", headers=cab, json=datos)
    assert r.status_code == 422


async def test_el_listado_trae_las_cifras_de_cada_cliente(superadmin, dos_tenants, client):
    a, b = dos_tenants
    cab = await _entrar_plataforma(client, superadmin)
    filas = {t["slug"]: t for t in (await client.get("/api/v1/admin/tenants", headers=cab)).json()}

    assert a.slug in filas and b.slug in filas
    assert filas[a.slug]["sedes"] == 2
    assert filas[a.slug]["usuarios"] == 2


async def test_suspender_corta_el_acceso_del_cliente(superadmin, dos_tenants, client):
    a, _ = dos_tenants
    cab = await _entrar_plataforma(client, superadmin)

    r = await client.patch(
        f"/api/v1/admin/tenants/{a.id}", headers=cab, json={"status": "suspendido"}
    )
    assert r.status_code == 200

    # El rechazo ocurre antes de mirar credenciales.
    fallo = await client.post(
        f"/api/v1/t/{a.slug}/auth/login", json={"email": a.admin, "password": CLAVE}
    )
    assert fallo.status_code == 403
    assert "suspendido" in fallo.json()["detail"]

    await client.patch(
        f"/api/v1/admin/tenants/{a.id}", headers=cab, json={"status": "activo"}
    )
    assert (await client.post(
        f"/api/v1/t/{a.slug}/auth/login", json={"email": a.admin, "password": CLAVE}
    )).status_code == 200


async def test_los_miembros_de_un_cliente_se_listan_con_sus_roles(
    superadmin, dos_tenants, client
):
    a, _ = dos_tenants
    cab = await _entrar_plataforma(client, superadmin)
    miembros = (await client.get(
        f"/api/v1/admin/tenants/{a.id}/usuarios", headers=cab
    )).json()

    por_correo = {m["email"]: m["roles"] for m in miembros}
    assert por_correo[a.admin] == ["tenant_admin"]
    assert por_correo[a.operario] == ["operator"]


async def test_agregar_un_miembro_desde_la_plataforma(superadmin, dos_tenants, client):
    a, _ = dos_tenants
    cab = await _entrar_plataforma(client, superadmin)
    correo = f"nuevo-{uuid.uuid4().hex[:6]}@prueba.com.co"

    r = await client.post(
        f"/api/v1/admin/tenants/{a.id}/usuarios",
        headers=cab,
        json={"email": correo, "nombre": "Persona Nueva",
              "password": "contrasenalarga1", "rol": "manager"},
    )
    assert r.status_code == 201

    token = await entrar(client, a.slug, correo, "contrasenalarga1")
    perfil = (await client.get(f"/api/v1/t/{a.slug}/auth/me", headers=cabecera(token))).json()
    assert perfil["roles"] == ["manager"]

    async with system_scope() as session:
        u = await session.scalar(select(User).where(User.email == correo))
        if u:
            await session.delete(u)


# ── Administradores de plataforma ────────────────────────────────────────

async def test_nadie_puede_quitarse_a_si_mismo_la_administracion(superadmin, client):
    """Es lo que garantiza que nunca quede la plataforma sin administradores:
    como solo se pueden quitar otros, quien ejecuta la acción siempre queda."""
    cab = await _entrar_plataforma(client, superadmin)
    yo = (await client.get("/api/v1/admin/me", headers=cab)).json()

    r = await client.delete(f"/api/v1/admin/usuarios/{yo['id']}", headers=cab)
    assert r.status_code == 409
    assert "ti mismo" in r.json()["detail"]


async def test_quitarle_la_administracion_a_otro_no_borra_la_persona(superadmin, client):
    """Puede seguir siendo usuario de algún parqueadero."""
    cab = await _entrar_plataforma(client, superadmin)
    correo = f"temporal-{uuid.uuid4().hex[:6]}@plataforma.com.co"
    creado = (await client.post(
        "/api/v1/admin/usuarios", headers=cab,
        json={"email": correo, "nombre": "Temporal", "password": "contrasenalarga1"},
    )).json()

    r = await client.delete(f"/api/v1/admin/usuarios/{creado['id']}", headers=cab)
    assert r.status_code == 204

    async with system_scope() as session:
        user = await session.scalar(select(User).where(User.email == correo))
        assert user is not None, "se borró la persona en vez de quitarle la marca"
        assert user.is_platform_admin is False
        await session.delete(user)


async def test_el_superadmin_crea_otro_superadmin(superadmin, client):
    cab = await _entrar_plataforma(client, superadmin)
    correo = f"otro-{uuid.uuid4().hex[:6]}@plataforma.com.co"

    r = await client.post(
        "/api/v1/admin/usuarios", headers=cab,
        json={"email": correo, "nombre": "Otro Admin", "password": "contrasenalarga1"},
    )
    assert r.status_code == 201

    # Y el nuevo puede entrar.
    entrada = await client.post(
        "/api/v1/admin/auth/login",
        json={"email": correo, "password": "contrasenalarga1"},
    )
    assert entrada.status_code == 200

    async with system_scope() as session:
        u = await session.scalar(select(User).where(User.email == correo))
        if u:
            await session.delete(u)


# ── Aislamiento ──────────────────────────────────────────────────────────

async def test_el_superadmin_ve_por_encima_pero_el_tenant_no(superadmin, dos_tenants, client):
    """La plataforma ve todos los clientes; una sesión de tenant sigue sin
    ver nada ajeno."""
    a, b = dos_tenants
    cab = await _entrar_plataforma(client, superadmin)
    slugs = {t["slug"] for t in (await client.get("/api/v1/admin/tenants", headers=cab)).json()}
    assert {a.slug, b.slug} <= slugs

    async with tenant_scope(a.id) as session:
        visibles = list((await session.scalars(select(Tenant.slug))).all())
    assert visibles == [a.slug]


async def test_las_acciones_de_plataforma_quedan_en_la_bitacora(superadmin, dos_tenants, client):
    from app.models.audit import AuditLog

    a, _ = dos_tenants
    cab = await _entrar_plataforma(client, superadmin)
    await client.patch(
        f"/api/v1/admin/tenants/{a.id}", headers=cab, json={"nombre": "Renombrado"}
    )

    async with system_scope() as session:
        acciones = set((await session.scalars(select(AuditLog.accion))).all())
    assert "plataforma.login" in acciones
    assert "plataforma.tenant_update" in acciones


async def test_un_tenant_suspendido_no_se_reactiva_solo(superadmin, dos_tenants, client):
    a, _ = dos_tenants
    cab = await _entrar_plataforma(client, superadmin)
    await client.patch(
        f"/api/v1/admin/tenants/{a.id}", headers=cab, json={"status": "suspendido"}
    )
    async with system_scope() as session:
        tenant = await session.get(Tenant, a.id)
        assert tenant.status is TenantStatus.SUSPENDIDO
