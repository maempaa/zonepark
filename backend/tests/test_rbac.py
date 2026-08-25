"""Roles, permisos y alcance por sede."""

from sqlalchemy import select

from app.db.session import tenant_scope
from app.models.audit import AuditLog
from app.models.parking_lot import ParkingLot

from .conftest import cabecera, entrar


async def test_el_admin_ve_todas_las_sedes(dos_tenants, client):
    a, _ = dos_tenants
    token = await entrar(client, a.slug, a.admin)
    sedes = (await client.get(f"/api/v1/t/{a.slug}/sedes", headers=cabecera(token))).json()
    assert {s["codigo"] for s in sedes} == {"S1", "S2"}


async def test_el_operario_solo_ve_la_sede_que_tiene_asignada(dos_tenants, client):
    """Alcance dentro del tenant: RLS aísla entre clientes, esto aísla dentro."""
    a, _ = dos_tenants
    token = await entrar(client, a.slug, a.operario)
    sedes = (await client.get(f"/api/v1/t/{a.slug}/sedes", headers=cabecera(token))).json()
    assert [s["id"] for s in sedes] == [str(a.sede_asignada)]


async def test_al_operario_le_falta_permiso_para_crear_sedes(dos_tenants, client):
    a, _ = dos_tenants
    token = await entrar(client, a.slug, a.operario)
    r = await client.post(
        f"/api/v1/t/{a.slug}/sedes",
        headers=cabecera(token),
        json={"codigo": "S9", "nombre": "Sede pirata"},
    )
    assert r.status_code == 403
    assert "lot:manage" in r.json()["detail"]


async def test_el_admin_si_puede_crear_una_sede(dos_tenants, client):
    a, _ = dos_tenants
    token = await entrar(client, a.slug, a.admin)
    r = await client.post(
        f"/api/v1/t/{a.slug}/sedes",
        headers=cabecera(token),
        json={"codigo": "S3", "nombre": "Sede nueva", "direccion": "Calle 1"},
    )
    assert r.status_code == 201
    creada = r.json()
    assert creada["codigo"] == "S3"
    assert creada["ticket_prefix"] == "S3"

    async with tenant_scope(a.id) as session:
        codigos = set((await session.scalars(select(ParkingLot.codigo))).all())
    assert codigos == {"S1", "S2", "S3"}


async def test_no_se_repite_el_codigo_de_sede(dos_tenants, client):
    a, _ = dos_tenants
    token = await entrar(client, a.slug, a.admin)
    r = await client.post(
        f"/api/v1/t/{a.slug}/sedes",
        headers=cabecera(token),
        json={"codigo": "S1", "nombre": "Repetida"},
    )
    assert r.status_code == 409


async def test_el_mismo_codigo_si_puede_existir_en_otro_tenant(dos_tenants, client):
    """Los códigos son únicos por tenant, no globalmente."""
    a, b = dos_tenants
    token_b = await entrar(client, b.slug, b.admin)
    r = await client.post(
        f"/api/v1/t/{b.slug}/sedes",
        headers=cabecera(token_b),
        json={"codigo": "S3", "nombre": "Sede de otro cliente"},
    )
    assert r.status_code == 201


async def test_crear_una_sede_queda_en_la_bitacora(dos_tenants, client):
    a, _ = dos_tenants
    token = await entrar(client, a.slug, a.admin)
    await client.post(
        f"/api/v1/t/{a.slug}/sedes",
        headers=cabecera(token),
        json={"codigo": "S4", "nombre": "Auditada"},
    )

    async with tenant_scope(a.id) as session:
        registros = list(
            (await session.scalars(select(AuditLog).where(AuditLog.accion == "sede.create"))).all()
        )

    assert len(registros) == 1
    assert registros[0].despues["codigo"] == "S4"
    assert registros[0].tenant_id == a.id


async def test_el_login_queda_en_la_bitacora(dos_tenants, client):
    a, _ = dos_tenants
    await entrar(client, a.slug, a.admin)

    async with tenant_scope(a.id) as session:
        registros = list(
            (await session.scalars(select(AuditLog).where(AuditLog.accion == "auth.login"))).all()
        )

    assert len(registros) == 1
    assert registros[0].actor_email == a.admin


async def test_la_bitacora_tambien_esta_aislada(dos_tenants, client):
    a, b = dos_tenants
    await entrar(client, a.slug, a.admin)
    await entrar(client, b.slug, b.admin)

    async with tenant_scope(a.id) as session:
        correos = set((await session.scalars(select(AuditLog.actor_email))).all())

    assert correos == {a.admin}
