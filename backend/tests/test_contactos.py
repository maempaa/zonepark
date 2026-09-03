"""El número al que se le manda el recibo, recordado por placa.

Es un dato personal de un cliente del parqueadero, así que lo que más
importa probar es que no se escape del tenant y que se pueda borrar.
"""

import pytest

from app.db.session import tenant_scope
from app.models.tenant import Tenant
from app.services.contactos import (
    TelefonoInvalido,
    contacto_de,
    normalizar_telefono,
    olvidar,
    recordar,
)

from .conftest import cabecera, entrar

# ── El número ────────────────────────────────────────────────────────────

def test_el_numero_se_limpia_pero_no_se_reformatea():
    """Quien teclea dicta lo que le dicen; solo se quitan los adornos."""
    assert normalizar_telefono("310 555 0101") == "3105550101"
    assert normalizar_telefono("(310) 555-0101") == "3105550101"
    assert normalizar_telefono("+57 310 555 0101") == "+573105550101"


def test_lo_que_no_es_un_telefono_se_rechaza():
    for malo in ["", "123", "abc", "1" * 16]:
        with pytest.raises(TelefonoInvalido):
            normalizar_telefono(malo)


# ── Recordar y olvidar ───────────────────────────────────────────────────

async def test_la_segunda_vez_ya_viene_puesto(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant = await session.get(Tenant, a.id)
        await recordar(session, tenant=tenant, placa="abc-123", telefono="310 555 0101")

        # La placa se busca normalizada: se teclea de cualquier forma.
        encontrado = await contacto_de(session, placa="ABC 123")
        assert encontrado is not None
        assert encontrado.telefono == "3105550101"
        assert encontrado.placa == "ABC123"


async def test_un_numero_nuevo_pisa_al_anterior(dos_tenants):
    """Se guarda el último que se usó, no un historial."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant = await session.get(Tenant, a.id)
        await recordar(session, tenant=tenant, placa="ABC123", telefono="3105550101")
        await recordar(session, tenant=tenant, placa="ABC123", telefono="3209998877")
        assert (await contacto_de(session, placa="ABC123")).telefono == "3209998877"


async def test_se_puede_borrar(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant = await session.get(Tenant, a.id)
        await recordar(session, tenant=tenant, placa="ABC123", telefono="3105550101")
        assert await olvidar(session, placa="ABC123") is True
        assert await contacto_de(session, placa="ABC123") is None


async def test_el_numero_no_cruza_de_parqueadero(dos_tenants):
    """RLS: la misma placa en dos parqueaderos son dos clientes distintos."""
    a, b = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant = await session.get(Tenant, a.id)
        await recordar(session, tenant=tenant, placa="ABC123", telefono="3105550101")

    async with tenant_scope(b.id) as session:
        assert await contacto_de(session, placa="ABC123") is None


# ── Por la API ───────────────────────────────────────────────────────────

async def test_el_circuito_completo_por_la_api(dos_tenants, client):
    a, _ = dos_tenants
    cab = cabecera(await entrar(client, a.slug, a.admin))

    ruta = f"/api/v1/t/{a.slug}/contactos/ABC123"
    assert (await client.get(ruta, headers=cab)).status_code == 404

    r = await client.put(
        f"/api/v1/t/{a.slug}/contactos/ABC123", headers=cab,
        json={"telefono": "310 555 0101"},
    )
    assert r.status_code == 200
    assert r.json()["telefono"] == "3105550101"

    r = await client.get(f"/api/v1/t/{a.slug}/contactos/abc123", headers=cab)
    assert r.status_code == 200, "la placa se busca normalizada"

    assert (await client.delete(ruta, headers=cab)).status_code == 204
    assert (await client.get(ruta, headers=cab)).status_code == 404


async def test_sin_sesion_no_se_leen_telefonos(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.get(f"/api/v1/t/{a.slug}/contactos/ABC123")
    assert r.status_code in (401, 403)


async def test_un_numero_invalido_se_rechaza(dos_tenants, client):
    a, _ = dos_tenants
    cab = cabecera(await entrar(client, a.slug, a.admin))
    r = await client.put(
        f"/api/v1/t/{a.slug}/contactos/ABC123", headers=cab, json={"telefono": "no-es"},
    )
    assert r.status_code == 422
