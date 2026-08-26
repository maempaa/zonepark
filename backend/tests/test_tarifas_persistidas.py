"""De la base al motor.

El motor está probado a fondo por su cuenta; lo que se verifica aquí es el
tramo que los une: que lo guardado en `rate_rules` se convierta en las
reglas correctas y que el aislamiento entre clientes también cubra las
tarifas.
"""

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.db.session import tenant_scope
from app.domain.pricing.motor import cotizar
from app.domain.pricing.snapshot import congelar, descongelar
from app.models.catalogo import ServiceItem, VehicleType
from app.models.tarifa import EstadoPlan, RatePlan, RateRule
from app.services.tarifas import (
    SinTarifaParaElVehiculo,
    festivos_entre,
    plan_vigente,
    reglas_del_plan,
)

BOGOTA = ZoneInfo("America/Bogota")


def en_bogota(dia: int, hora: int, minuto: int = 0) -> datetime:
    return datetime(2026, 8, dia, hora, minuto, tzinfo=BOGOTA).astimezone(UTC)


async def _reglas(session, t, codigo_tipo: str):
    plan = await plan_vigente(
        session, parking_lot_id=t.sede_asignada, cuando=en_bogota(24, 8).date()
    )
    return plan, await reglas_del_plan(session, plan=plan, vehicle_type_id=t.tipos[codigo_tipo])


# ── El plan sembrado cobra lo que dice cobrar ────────────────────────────

async def test_el_carro_paga_hora_o_fraccion(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        _, reglas = await _reglas(session, a, "carro")
        c = cotizar(reglas=reglas, entrada=en_bogota(24, 8),
                    salida=en_bogota(24, 10, 17), zona=BOGOTA)
    assert c.total == Decimal("9000.00")  # tres fracciones de hora


async def test_la_moto_paga_media_hora_o_fraccion(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        _, reglas = await _reglas(session, a, "moto")
        c = cotizar(reglas=reglas, entrada=en_bogota(24, 8),
                    salida=en_bogota(24, 9, 5), zona=BOGOTA)
    assert c.total == Decimal("2700.00")  # tres fracciones de 30 min


async def test_la_bicicleta_paga_tarifa_plena(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        _, reglas = await _reglas(session, a, "bicicleta")
        c = cotizar(reglas=reglas, entrada=en_bogota(24, 8),
                    salida=en_bogota(24, 18), zona=BOGOTA)
    assert c.total == Decimal("2000.00")


async def test_la_cortesia_del_plan_funciona(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        _, reglas = await _reglas(session, a, "carro")
        c = cotizar(reglas=reglas, entrada=en_bogota(24, 8),
                    salida=en_bogota(24, 8, 12), zona=BOGOTA)
    assert c.en_cortesia and c.total == Decimal("0.00")


async def test_la_tarifa_nocturna_del_plan_se_aplica(dos_tenants):
    """19:00 → 22:00: una hora diurna a $3.000 y dos nocturnas a $2.000."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        _, reglas = await _reglas(session, a, "carro")
        c = cotizar(reglas=reglas, entrada=en_bogota(24, 19),
                    salida=en_bogota(24, 22), zona=BOGOTA)
    assert c.total == Decimal("7000.00")


async def test_el_tope_diario_del_plan_se_aplica(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        _, reglas = await _reglas(session, a, "carro")
        c = cotizar(reglas=reglas, entrada=en_bogota(24, 6),
                    salida=en_bogota(24, 20), zona=BOGOTA)
    assert c.tope_aplicado
    assert c.total == Decimal("22000.00")


async def test_un_tipo_sin_tarifa_falla_claro(dos_tenants):
    """Mejor un error nombrando el tipo que cobrar cero sin avisar."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        plan = await plan_vigente(session, parking_lot_id=a.sede_asignada,
                                  cuando=en_bogota(24, 8).date())
        huerfano = VehicleType(tenant_id=a.id, codigo="patineta", nombre="Patineta")
        session.add(huerfano)
        await session.flush()

        with pytest.raises(SinTarifaParaElVehiculo, match="patineta"):
            await reglas_del_plan(session, plan=plan, vehicle_type_id=huerfano.id)


# ── Congelado desde datos reales ─────────────────────────────────────────

async def test_el_snapshot_de_un_plan_real_cotiza_igual(dos_tenants):
    a, _ = dos_tenants
    entrada, salida = en_bogota(24, 19), en_bogota(25, 7)

    async with tenant_scope(a.id) as session:
        plan, reglas = await _reglas(session, a, "carro")
        directo = cotizar(reglas=reglas, entrada=entrada, salida=salida, zona=BOGOTA)
        snapshot = json.loads(json.dumps(
            congelar(reglas, plan_codigo=plan.codigo, plan_version=plan.version)
        ))

    congelado = cotizar(reglas=descongelar(snapshot), entrada=entrada, salida=salida, zona=BOGOTA)
    assert congelado.total == directo.total
    assert congelado.lineas == directo.lineas


async def test_subir_la_tarifa_no_cambia_lo_ya_congelado(dos_tenants):
    """El escenario del plan: el precio sube con el carro adentro."""
    a, _ = dos_tenants
    entrada, salida = en_bogota(24, 8), en_bogota(24, 11)

    async with tenant_scope(a.id) as session:
        plan, reglas = await _reglas(session, a, "carro")
        snapshot = json.loads(json.dumps(
            congelar(reglas, plan_codigo=plan.codigo, plan_version=plan.version)
        ))

        # El administrador sube la tarifa mientras el ticket sigue abierto.
        regla = await session.scalar(
            select(RateRule).where(RateRule.codigo == "carro-general")
        )
        regla.precio_bloque = Decimal("5000.00")
        await session.flush()

        _, nuevas = await _reglas(session, a, "carro")
        con_la_nueva = cotizar(reglas=nuevas, entrada=entrada, salida=salida, zona=BOGOTA)

    con_la_congelada = cotizar(reglas=descongelar(snapshot),
                               entrada=entrada, salida=salida, zona=BOGOTA)
    assert con_la_congelada.total == Decimal("9000.00")
    assert con_la_nueva.total == Decimal("15000.00")


# ── Festivos ─────────────────────────────────────────────────────────────

async def test_los_festivos_se_leen_del_calendario_del_tenant(dos_tenants):
    from datetime import date

    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        festivos = await festivos_entre(session, desde=date(2026, 12, 1), hasta=date(2026, 12, 31))
    assert date(2026, 12, 25) in festivos
    assert date(2026, 12, 24) not in festivos


# ── Aislamiento: las tarifas también son datos del cliente ───────────────

async def test_las_tarifas_de_un_tenant_no_se_ven_desde_otro(dos_tenants):
    a, b = dos_tenants
    async with tenant_scope(a.id) as session:
        planes = list((await session.scalars(select(RatePlan))).all())
        reglas = list((await session.scalars(select(RateRule))).all())
        tipos = list((await session.scalars(select(VehicleType))).all())
        articulos = list((await session.scalars(select(ServiceItem))).all())

    for coleccion in (planes, reglas, tipos, articulos):
        assert coleccion, "el fixture no sembró datos"
        assert {x.tenant_id for x in coleccion} == {a.id}


async def test_no_se_puede_leer_el_plan_de_otro_tenant_ni_forzando_el_id(dos_tenants):
    a, b = dos_tenants
    async with tenant_scope(b.id) as session:
        plan_de_b = await plan_vigente(session, parking_lot_id=b.sede_asignada,
                                       cuando=en_bogota(24, 8).date())

    async with tenant_scope(a.id) as session:
        assert await session.get(RatePlan, plan_de_b.id) is None


async def test_cada_tenant_puede_tener_su_propio_precio(dos_tenants):
    """Los códigos de tarifa se repiten entre clientes sin colisionar."""
    a, b = dos_tenants
    async with tenant_scope(b.id) as session:
        regla = await session.scalar(select(RateRule).where(RateRule.codigo == "carro-general"))
        regla.precio_bloque = Decimal("7500.00")
        await session.flush()

    async with tenant_scope(a.id) as session:
        _, reglas_a = await _reglas(session, a, "carro")
    async with tenant_scope(b.id) as session:
        _, reglas_b = await _reglas(session, b, "carro")

    una_hora = timedelta(hours=1)
    total_a = cotizar(reglas=reglas_a, entrada=en_bogota(24, 8),
                      salida=en_bogota(24, 8) + una_hora, zona=BOGOTA).total
    total_b = cotizar(reglas=reglas_b, entrada=en_bogota(24, 8),
                      salida=en_bogota(24, 8) + una_hora, zona=BOGOTA).total
    assert total_a == Decimal("3000.00")
    assert total_b == Decimal("7500.00")


async def test_un_plan_archivado_deja_de_estar_vigente(dos_tenants):
    a, _ = dos_tenants
    from app.services.tarifas import SinPlanVigente

    async with tenant_scope(a.id) as session:
        plan = await plan_vigente(session, parking_lot_id=a.sede_asignada,
                                  cuando=en_bogota(24, 8).date())
        plan.estado = EstadoPlan.ARCHIVADO
        await session.flush()

        with pytest.raises(SinPlanVigente):
            await plan_vigente(session, parking_lot_id=a.sede_asignada,
                               cuando=en_bogota(24, 8).date())
