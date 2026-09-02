"""La tarifa se acuerda al recibir el vehículo, no al entregarlo.

Lo que se prueba es la promesa: si al cliente se le dijo "por hora" cuando
dejó el carro, eso es lo que ve en su recibo y eso es lo que se le cobra
por defecto, aunque el motor hubiera elegido otra cosa.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import tenant_scope
from app.models.catalogo import VehicleType
from app.models.parking_lot import ParkingLot
from app.models.tarifa import RatePlan, RateRule
from app.models.tenant import Tenant
from app.models.ticket import MetodoPago
from app.services.recibo import recibo_publico
from app.services.tickets import (
    OpcionDesconocida,
    abrir_ticket,
    cerrar_ticket,
    opciones_de_cobro,
)

from .conftest import cabecera, entrar

ENTRADA = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)


async def _plena_para_carro(session, tenant_id):
    """Agrega una tarifa plena al plan activo, para tener dos donde elegir."""
    plan = await session.scalar(
        select(RatePlan).where(RatePlan.codigo == "general", RatePlan.estado == "activo")
    )
    tipo = await session.scalar(select(VehicleType).where(VehicleType.codigo == "carro"))
    session.add(
        RateRule(
            tenant_id=tenant_id, rate_plan_id=plan.id, vehicle_type_id=tipo.id,
            codigo="carro-plena", nombre="Todo el día", modo="plena",
            precio_plena=Decimal("12000.00"),
        )
    )
    await session.flush()
    return tipo


async def _abrir(session, t, tipo, **extra):
    tenant = await session.get(Tenant, t.id)
    sede = await session.get(ParkingLot, t.sede_asignada)
    return await abrir_ticket(
        session, tenant=tenant, sede=sede, tipo=tipo, placa="ABC123",
        entrada=ENTRADA, membership_id=None, **extra,
    )


# ── Se guarda y manda ────────────────────────────────────────────────────

async def test_sin_elegir_nada_se_comporta_como_antes(dos_tenants):
    """Los tickets que ya existían no tienen tarifa acordada."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tipo = await _plena_para_carro(session, a.id)
        ticket = await _abrir(session, a, tipo)
        assert ticket.opcion_cobro is None

        tenant = await session.get(Tenant, a.id)
        opciones = await opciones_de_cobro(
            session, tenant=tenant, ticket=ticket, ahora=ENTRADA + timedelta(minutes=90)
        )
    # La primera sigue siendo la automática del motor.
    assert opciones[0].recomendada is True


async def test_la_acordada_queda_primera_y_recomendada(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tipo = await _plena_para_carro(session, a.id)
        ticket = await _abrir(session, a, tipo, opcion_cobro="carro-plena")
        tenant = await session.get(Tenant, a.id)
        opciones = await opciones_de_cobro(
            session, tenant=tenant, ticket=ticket, ahora=ENTRADA + timedelta(minutes=90)
        )

    assert opciones[0].codigo == "carro-plena"
    assert opciones[0].recomendada is True
    assert opciones[0].cotizacion.total == Decimal("12000.00")
    # Las demás siguen ofreciéndose: quien cobra puede cambiarla.
    assert len(opciones) > 1
    assert all(not o.recomendada for o in opciones[1:])


async def test_con_tarifa_acordada_no_se_ofrece_la_automatica(dos_tenants):
    """Aparecerle la nocturna en la salida a quien se le prometió una plena
    es justo la discusión que el acuerdo venía a evitar."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tipo = await _plena_para_carro(session, a.id)
        ticket = await _abrir(session, a, tipo, opcion_cobro="carro-plena")
        tenant = await session.get(Tenant, a.id)
        # Dentro de la franja nocturna del plan sembrado.
        nocturno = ENTRADA.replace(hour=3) + timedelta(days=1)
        opciones = await opciones_de_cobro(
            session, tenant=tenant, ticket=ticket, ahora=nocturno
        )

    assert "carro-nocturna" not in {o.codigo for o in opciones}
    assert opciones[0].codigo == "carro-plena"


async def test_se_cobra_la_acordada_sin_repetirla_en_el_cobro(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tipo = await _plena_para_carro(session, a.id)
        ticket = await _abrir(session, a, tipo, opcion_cobro="carro-plena")
        tenant = await session.get(Tenant, a.id)
        _, pago, _ = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id,
            ahora=ENTRADA + timedelta(minutes=90),
            metodo=MetodoPago.EFECTIVO, recibido=Decimal("20000"), membership_id=None,
        )

    assert pago.regla_aplicada == "carro-plena"
    assert pago.monto == Decimal("12000.00")


async def test_quien_cobra_todavia_puede_cambiarla(dos_tenants):
    """El acuerdo es el valor por defecto, no una jaula."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tipo = await _plena_para_carro(session, a.id)
        ticket = await _abrir(session, a, tipo, opcion_cobro="carro-plena")
        tenant = await session.get(Tenant, a.id)
        _, pago, _ = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id,
            ahora=ENTRADA + timedelta(minutes=90),
            metodo=MetodoPago.EFECTIVO, recibido=Decimal("50000"),
            membership_id=None, opcion="carro-general",
        )

    assert pago.regla_aplicada == "carro-general"


async def test_una_tarifa_que_no_existe_se_rechaza_al_ingresar(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tipo = await _plena_para_carro(session, a.id)
        with pytest.raises(OpcionDesconocida):
            await _abrir(session, a, tipo, opcion_cobro="carro-inventada")


async def test_una_franja_no_se_puede_acordar(dos_tenants):
    """La nocturna es una variante horaria, no una forma de cobro que el
    operario pueda prometerle a alguien a las 8 de la mañana."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tipo = await _plena_para_carro(session, a.id)
        with pytest.raises(OpcionDesconocida):
            await _abrir(session, a, tipo, opcion_cobro="carro-nocturna")


# ── Lo que ve el cliente ─────────────────────────────────────────────────

async def test_el_recibo_muestra_la_tarifa_acordada(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tipo = await _plena_para_carro(session, a.id)
        ticket = await _abrir(session, a, tipo, opcion_cobro="carro-plena")
        tenant = await session.get(Tenant, a.id)
        r = await recibo_publico(
            session, tenant=tenant, token=ticket.token_publico,
            ahora=ENTRADA + timedelta(minutes=137),
        )

    assert r.acordada is True
    assert r.tarifa == "Todo el día"
    assert r.total == Decimal("12000.00")


# ── Por la API ───────────────────────────────────────────────────────────

async def test_la_pantalla_de_ingreso_recibe_las_tarifas(dos_tenants, client):
    a, _ = dos_tenants
    cab = cabecera(await entrar(client, a.slug, a.admin))
    async with tenant_scope(a.id) as session:
        await _plena_para_carro(session, a.id)

    r = await client.get(
        f"/api/v1/t/{a.slug}/tarifas/ingreso?parking_lot_id={a.sede_asignada}",
        headers=cab,
    )
    assert r.status_code == 200
    carro = next(t for t in r.json() if t["vehicle_type_id"] == str(a.tipos["carro"]))
    codigos = {o["codigo"] for o in carro["opciones"]}
    assert {"carro-general", "carro-plena"} <= codigos
    assert "carro-nocturna" not in codigos, "una franja no se elige a mano"
    # El plan sembrado tiene nocturna: hay que poder dejarla actuar.
    assert carro["admite_automatica"] is True
    assert sum(1 for o in carro["opciones"] if o["predeterminada"]) == 1
    assert all(o["descripcion"] for o in carro["opciones"])
