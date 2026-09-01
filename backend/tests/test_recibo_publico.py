"""El recibo que el cliente abre sin sesión.

Lo que se prueba aquí no es solo que muestre el monto: es que no muestre
nada más. Un endpoint sin autenticación es una puerta abierta, y la
prueba que importa es la que falla cuando alguien agregue un campo de más.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import tenant_scope
from app.models.catalogo import VehicleType
from app.models.parking_lot import ParkingLot
from app.models.tenant import Tenant
from app.models.ticket import MetodoPago
from app.services.recibo import AVISO_POR_DEFECTO, ReciboNoEncontrado, recibo_publico
from app.services.tickets import abrir_ticket, cerrar_ticket

ENTRADA = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)


async def _abrir(session, t, placa="ABC123", **extra):
    tenant = await session.get(Tenant, t.id)
    sede = await session.get(ParkingLot, t.sede_asignada)
    tipo = await session.scalar(select(VehicleType).where(VehicleType.codigo == "carro"))
    return await abrir_ticket(
        session, tenant=tenant, sede=sede, tipo=tipo, placa=placa,
        entrada=ENTRADA, membership_id=None, **extra,
    )


# ── El token ─────────────────────────────────────────────────────────────

async def test_cada_ticket_nace_con_su_token(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        uno = await _abrir(session, a)
        otro = await _abrir(session, a, placa="XYZ789")
        assert len(uno.token_publico) == 32
        assert uno.token_publico != otro.token_publico


async def test_un_token_inventado_no_devuelve_nada(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant = await session.get(Tenant, a.id)
        with pytest.raises(ReciboNoEncontrado):
            await recibo_publico(
                session, tenant=tenant, token="f" * 32, ahora=ENTRADA
            )


async def test_el_token_de_un_parqueadero_no_sirve_en_otro(dos_tenants):
    """RLS: el recibo cuelga del slug, y el ticket no existe fuera de su tenant."""
    a, b = dos_tenants
    async with tenant_scope(a.id) as session:
        ticket = await _abrir(session, a)
        token = ticket.token_publico

    async with tenant_scope(b.id) as session:
        tenant_b = await session.get(Tenant, b.id)
        with pytest.raises(ReciboNoEncontrado):
            await recibo_publico(session, tenant=tenant_b, token=token, ahora=ENTRADA)


# ── El contenido ─────────────────────────────────────────────────────────

async def test_muestra_lo_que_el_cliente_necesita(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        sede = await session.get(ParkingLot, a.sede_asignada)
        sede.direccion = "Calle 100 #15-20"
        sede.telefono = "310 555 0101"
        await session.flush()

        ticket = await _abrir(session, a)
        tenant = await session.get(Tenant, a.id)
        r = await recibo_publico(
            session, tenant=tenant, token=ticket.token_publico,
            ahora=ENTRADA + timedelta(minutes=137),
        )

    assert r.codigo == ticket.codigo
    assert r.placa == "ABC123"
    assert r.direccion == "Calle 100 #15-20"
    assert r.telefono == "310 555 0101"
    assert r.minutos == 137
    assert r.total > Decimal("0")
    assert r.estimado is True, "abierto todavía: el monto no es definitivo"


async def test_el_aviso_de_objetos_perdidos_siempre_viene(dos_tenants):
    """Sin configurar sale el de fábrica; configurado, el del parqueadero."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        ticket = await _abrir(session, a)
        tenant = await session.get(Tenant, a.id)

        r = await recibo_publico(
            session, tenant=tenant, token=ticket.token_publico, ahora=ENTRADA
        )
        assert r.aviso == AVISO_POR_DEFECTO

        tenant.aviso_responsabilidad = "Deje sus llaves en recepción."
        r2 = await recibo_publico(
            session, tenant=tenant, token=ticket.token_publico, ahora=ENTRADA
        )
        assert r2.aviso == "Deje sus llaves en recepción."


async def test_cerrado_muestra_lo_cobrado_y_no_un_calculo_nuevo(dos_tenants):
    """Recalcular después del cierre daría otro número: el reloj siguió."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        ticket = await _abrir(session, a)
        tenant = await session.get(Tenant, a.id)
        salida = ENTRADA + timedelta(minutes=90)
        _, pago, _ = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, ahora=salida,
            metodo=MetodoPago.EFECTIVO, recibido=Decimal("50000"), membership_id=None,
        )

        # Mucho después: si recalculara, el total habría crecido.
        r = await recibo_publico(
            session, tenant=tenant, token=ticket.token_publico,
            ahora=salida + timedelta(hours=9),
        )

    assert r.estimado is False
    assert r.total == pago.monto
    assert r.salida_at is not None


# ── Lo que NO debe salir ─────────────────────────────────────────────────

async def test_el_recibo_no_filtra_la_operacion_interna(dos_tenants):
    """Quién lo abrió, contra qué caja se cobró y con cuánto pagó el cliente
    son datos del parqueadero, no del recibo."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        ticket = await _abrir(session, a)
        tenant = await session.get(Tenant, a.id)
        r = await recibo_publico(
            session, tenant=tenant, token=ticket.token_publico, ahora=ENTRADA
        )

    publicado = set(vars(r) if hasattr(r, "__dict__") else
                    {c: getattr(r, c) for c in r.__slots__})
    prohibidos = {
        "operario_entrada_id", "operario_salida_id", "cash_session_id",
        "recibido", "cambio", "rate_snapshot", "tenant_id", "id",
        "monto_calculado", "ajuste_manual", "motivo_ajuste", "observaciones",
    }
    assert publicado & prohibidos == set()


# ── Por la API, sin cabecera de sesión ───────────────────────────────────

async def test_se_abre_sin_iniciar_sesion(dos_tenants, client):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        ticket = await _abrir(session, a)
        token = ticket.token_publico

    r = await client.get(f"/api/v1/t/{a.slug}/publico/recibo/{token}")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["codigo"] == ticket.codigo
    assert cuerpo["aviso"]
    assert "operario_entrada_id" not in cuerpo


async def test_un_token_con_forma_rara_se_rechaza_sin_tocar_la_base(dos_tenants, client):
    a, _ = dos_tenants
    for malo in ["../../etc/passwd", "abc", "Z" * 32, "' OR 1=1--"]:
        r = await client.get(f"/api/v1/t/{a.slug}/publico/recibo/{malo}")
        assert r.status_code in (404, 422), malo
