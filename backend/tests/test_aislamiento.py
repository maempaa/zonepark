"""Criterio de aceptación de la fase 1.

Un tenant no puede leer ni un solo registro de otro, ni siquiera forzando
los identificadores. Si alguna de estas pruebas se pone en rojo, hay una
fuga entre clientes.
"""

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from app.db.session import system_scope, tenant_scope
from app.models.parking_lot import ParkingLot
from app.models.tenant import Tenant
from app.models.user import Membership, User

from .conftest import cabecera, entrar


async def test_la_sesion_de_un_tenant_solo_ve_lo_suyo(dos_tenants):
    a, b = dos_tenants
    async with tenant_scope(a.id) as session:
        tenants = list((await session.scalars(select(Tenant))).all())
        assert [t.id for t in tenants] == [a.id]

        sedes = list((await session.scalars(select(ParkingLot))).all())
        assert {s.tenant_id for s in sedes} == {a.id}


async def test_forzar_el_id_del_otro_tenant_no_devuelve_nada(dos_tenants):
    """El caso importante: la consulta pide explícitamente datos ajenos."""
    a, b = dos_tenants
    async with tenant_scope(a.id) as session:
        assert await session.get(Tenant, b.id) is None
        assert await session.get(ParkingLot, b.sede_asignada) is None

        ajenas = list(
            (await session.scalars(select(ParkingLot).where(ParkingLot.tenant_id == b.id))).all()
        )
        assert ajenas == []


async def test_no_se_ven_los_usuarios_del_otro_tenant(dos_tenants):
    a, b = dos_tenants
    async with tenant_scope(a.id) as session:
        correos = set((await session.scalars(select(User.email))).all())
        assert a.admin in correos
        assert b.admin not in correos

        membresias = list((await session.scalars(select(Membership))).all())
        assert {m.tenant_id for m in membresias} == {a.id}


async def test_no_se_puede_escribir_en_el_otro_tenant(dos_tenants):
    """RLS también corta las escrituras, no solo las lecturas.

    Postgres rechaza el INSERT por la cláusula WITH CHECK de la política.
    """
    a, b = dos_tenants
    with pytest.raises(DBAPIError) as error:
        async with tenant_scope(a.id) as session:
            session.add(ParkingLot(tenant_id=b.id, codigo="ROBO", nombre="Sede robada"))
            await session.flush()

    assert "row-level security" in str(error.value)

    # Y no quedó rastro de la fila.
    async with system_scope() as session:
        robadas = list(
            (await session.scalars(select(ParkingLot).where(ParkingLot.codigo == "ROBO"))).all()
        )
    assert robadas == []


async def test_sin_tenant_fijado_no_se_ve_nada(dos_tenants):
    """Falla cerrado: una sesión con el rol de aplicación y sin tenant ve cero filas."""
    a, _ = dos_tenants
    async with system_scope() as session:
        # Reproduce lo que hace la sesión de tenant pero sin fijar app.tenant_id.
        await session.execute(text("SET LOCAL ROLE zonepark_app"))
        assert (await session.scalar(select(Tenant.id).limit(1))) is None
        assert (await session.scalar(select(ParkingLot.id).limit(1))) is None


async def test_el_contexto_sobrevive_a_un_commit_intermedio(dos_tenants):
    """Regresión: `SET LOCAL` solo dura la transacción en curso.

    Si un servicio hace commit y sigue consultando, SQLAlchemy abre una
    transacción nueva. Sin volver a aplicar el contexto, esa segunda
    transacción correría como dueño y vería todos los tenants.
    """
    a, b = dos_tenants
    async with tenant_scope(a.id) as session:
        primeros = list((await session.scalars(select(Tenant.id))).all())
        assert primeros == [a.id]

        await session.commit()  # cierra la transacción

        segundos = list((await session.scalars(select(Tenant.id))).all())
        assert segundos == [a.id], "El contexto de tenant se perdió tras el commit"


async def test_credenciales_validas_no_sirven_en_otro_parqueadero(dos_tenants, client):
    a, b = dos_tenants
    r = await client.post(
        f"/api/v1/t/{b.slug}/auth/login",
        json={"email": a.admin, "password": "prueba12345"},
    )
    assert r.status_code == 401


async def test_el_token_de_un_tenant_se_rechaza_en_la_ruta_de_otro(dos_tenants, client):
    a, b = dos_tenants
    token = await entrar(client, a.slug, a.admin)
    r = await client.get(f"/api/v1/t/{b.slug}/auth/me", headers=cabecera(token))
    assert r.status_code == 403
    assert "no corresponde" in r.json()["detail"]


async def test_las_sedes_no_se_cruzan_entre_tenants(dos_tenants, client):
    a, b = dos_tenants
    token_a = await entrar(client, a.slug, a.admin)
    token_b = await entrar(client, b.slug, b.admin)

    respuesta_a = await client.get(f"/api/v1/t/{a.slug}/sedes", headers=cabecera(token_a))
    respuesta_b = await client.get(f"/api/v1/t/{b.slug}/sedes", headers=cabecera(token_b))
    ids_a = {s["id"] for s in respuesta_a.json()}
    ids_b = {s["id"] for s in respuesta_b.json()}

    assert ids_a and ids_b
    assert ids_a.isdisjoint(ids_b)
