"""El número al que se le manda el recibo, recordado por placa.

Es un dato personal de un cliente del parqueadero, así que lo que más
importa probar es que no se escape del tenant y que se pueda borrar.
"""

import pytest

from app.db.session import tenant_scope
from app.models.tenant import Tenant
from app.services.contactos import (
    CorreoInvalido,
    SinDondeMandarlo,
    TelefonoInvalido,
    contacto_de,
    normalizar_correo,
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


# ── El correo ────────────────────────────────────────────────────────────

def test_el_correo_se_recorta_y_baja_a_minusculas():
    assert normalizar_correo("  Ana.Perez@Gmail.COM ") == "ana.perez@gmail.com"


def test_lo_que_no_tiene_forma_de_correo_se_rechaza():
    for malo in ["", "ana", "ana@", "@gmail.com", "ana perez@gmail.com", "ana@gmail"]:
        with pytest.raises(CorreoInvalido):
            normalizar_correo(malo)


async def test_guardar_el_correo_no_borra_el_whatsapp(dos_tenants):
    """Quien manda el recibo por correo hoy no pierde el número de ayer."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant = await session.get(Tenant, a.id)
        await recordar(session, tenant=tenant, placa="ABC123", telefono="3105550101")
        await recordar(session, tenant=tenant, placa="ABC123", correo="ana@gmail.com")

        c = await contacto_de(session, placa="ABC123")
        assert c.telefono == "3105550101"
        assert c.correo == "ana@gmail.com"


async def test_se_puede_guardar_solo_el_correo(dos_tenants):
    """Un cliente que solo da su correo no obliga a inventarse un número."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant = await session.get(Tenant, a.id)
        c = await recordar(session, tenant=tenant, placa="XYZ789", correo="ana@gmail.com")
        assert c.telefono is None
        assert c.correo == "ana@gmail.com"


async def test_sin_ninguno_de_los_dos_no_hay_nada_que_guardar(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant = await session.get(Tenant, a.id)
        with pytest.raises(SinDondeMandarlo):
            await recordar(session, tenant=tenant, placa="ABC123", telefono="  ")


async def test_el_correo_por_la_api(dos_tenants, client):
    a, _ = dos_tenants
    cab = cabecera(await entrar(client, a.slug, a.admin))
    ruta = f"/api/v1/t/{a.slug}/contactos/ABC123"

    r = await client.put(ruta, headers=cab, json={"correo": "Ana@Gmail.com"})
    assert r.status_code == 200
    assert r.json() == {"placa": "ABC123", "telefono": None, "correo": "ana@gmail.com"}

    r = await client.put(ruta, headers=cab, json={"telefono": "310 555 0101"})
    assert r.json()["correo"] == "ana@gmail.com", "el correo sobrevive"
    assert r.json()["telefono"] == "3105550101"

    assert (await client.put(ruta, headers=cab, json={})).status_code == 422
    assert (
        await client.put(ruta, headers=cab, json={"correo": "no-es-correo"})
    ).status_code == 422
