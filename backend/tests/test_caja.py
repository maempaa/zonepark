"""Turnos de caja y arqueo.

El arqueo es dinero: cada regla de cómo se calcula el esperado tiene aquí
su prueba.
"""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.session import tenant_scope
from app.models.caja import CashShift, EstadoTurno, TipoMovimiento
from app.models.catalogo import ServiceItem, VehicleType
from app.models.parking_lot import ParkingLot
from app.models.tenant import Tenant
from app.models.ticket import MetodoPago
from app.models.user import Membership
from app.services.caja import (
    TurnoNoOperable,
    TurnoYaAbierto,
    abrir_turno,
    calcular_arqueo,
    cerrar_turno,
    registrar_movimiento,
    turno_abierto_de,
)
from app.services.tickets import abrir_ticket, agregar_item, cerrar_ticket

ENTRADA = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)
DOS_HORAS = ENTRADA + timedelta(minutes=137)


async def _ctx(session, t):
    tenant = await session.get(Tenant, t.id)
    sede = await session.get(ParkingLot, t.sede_asignada)
    membresia = await session.scalar(
        select(Membership).where(Membership.tenant_id == t.id).limit(1)
    )
    return tenant, sede, membresia


async def _turno(session, t, base="50000.00"):
    tenant, sede, membresia = await _ctx(session, t)
    turno = await abrir_turno(
        session, tenant=tenant, sede=sede, membership_id=membresia.id,
        base_inicial=Decimal(base), ahora=ENTRADA,
    )
    return tenant, sede, membresia, turno


async def _cobrar(session, tenant, t, membresia, *, metodo=MetodoPago.EFECTIVO,
                 recibido=None, placa="AAA111", salida=DOS_HORAS, item=None):
    sede = await session.get(ParkingLot, t.sede_asignada)
    tipo = await session.scalar(select(VehicleType).where(VehicleType.codigo == "carro"))
    ticket = await abrir_ticket(
        session, tenant=tenant, sede=sede, tipo=tipo, placa=placa,
        entrada=ENTRADA, membership_id=membresia.id if membresia else None,
    )
    if item:
        articulo = await session.scalar(select(ServiceItem).where(ServiceItem.codigo == item))
        await agregar_item(session, tenant=tenant, ticket=ticket, articulo=articulo)

    return await cerrar_ticket(
        session, tenant=tenant, ticket_id=ticket.id, metodo=metodo, ahora=salida,
        membership_id=membresia.id if membresia else None, recibido=recibido,
    )


# ── Apertura ─────────────────────────────────────────────────────────────

async def test_al_abrir_el_esperado_es_la_base(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        _, _, _, turno = await _turno(session, a)
        arqueo = await calcular_arqueo(session, turno=turno)

    assert turno.estado is EstadoTurno.ABIERTO
    assert arqueo.esperado == Decimal("50000.00")
    assert arqueo.tickets_cobrados == 0


async def test_no_se_pueden_abrir_dos_turnos_a_la_vez(dos_tenants):
    """Un doble toque no puede dejar dos turnos abiertos: el arqueo no cuadraría."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, sede, membresia, _ = await _turno(session, a)
        with pytest.raises(TurnoYaAbierto):
            await abrir_turno(
                session, tenant=tenant, sede=sede, membership_id=membresia.id,
                base_inicial=Decimal("10000"), ahora=ENTRADA,
            )


async def test_tras_cerrar_se_puede_abrir_otro(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, sede, membresia, turno = await _turno(session, a)
        await cerrar_turno(session, turno=turno, contado=Decimal("50000"), ahora=DOS_HORAS)
        segundo = await abrir_turno(
            session, tenant=tenant, sede=sede, membership_id=membresia.id,
            base_inicial=Decimal("30000"), ahora=DOS_HORAS,
        )
    assert segundo.estado is EstadoTurno.ABIERTO


# ── Qué entra en el esperado ─────────────────────────────────────────────

async def test_el_efectivo_cobrado_suma_al_esperado(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia, turno = await _turno(session, a)
        await _cobrar(session, tenant, a, membresia)
        arqueo = await calcular_arqueo(session, turno=turno)

    # 50.000 de base + 9.000 de tres fracciones de hora
    assert arqueo.efectivo_cobrado == Decimal("9000.00")
    assert arqueo.esperado == Decimal("59000.00")
    assert arqueo.tickets_cobrados == 1


async def test_el_cambio_entregado_no_infla_el_esperado(dos_tenants):
    """El cliente paga con 50.000 por un servicio de 9.000: quedan 9.000."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia, turno = await _turno(session, a)
        _, pago, _ = await _cobrar(
            session, tenant, a, membresia, recibido=Decimal("50000.00")
        )
        arqueo = await calcular_arqueo(session, turno=turno)

    assert pago.cambio == Decimal("41000.00")
    assert arqueo.esperado == Decimal("59000.00"), "se sumó lo recibido en vez del cobro"


async def test_la_tarjeta_no_entra_en_el_esperado(dos_tenants):
    """No llega al cajón: incluirla descuadraría todos los turnos."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia, turno = await _turno(session, a)
        await _cobrar(session, tenant, a, membresia, metodo=MetodoPago.TARJETA)
        arqueo = await calcular_arqueo(session, turno=turno)

    assert arqueo.esperado == Decimal("50000.00")
    assert arqueo.por_metodo["tarjeta"] == Decimal("9000.00")
    assert arqueo.tickets_cobrados == 1, "el cobro debe seguir contándose"


async def test_los_movimientos_manuales_ajustan_el_esperado(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia, turno = await _turno(session, a)
        await registrar_movimiento(
            session, tenant=tenant, turno=turno, tipo=TipoMovimiento.EGRESO,
            concepto="Escoba", monto=Decimal("12000"), membership_id=membresia.id,
        )
        await registrar_movimiento(
            session, tenant=tenant, turno=turno, tipo=TipoMovimiento.INGRESO,
            concepto="Base adicional", monto=Decimal("20000"), membership_id=membresia.id,
        )
        arqueo = await calcular_arqueo(session, turno=turno)

    assert arqueo.egresos_manuales == Decimal("12000.00")
    assert arqueo.ingresos_manuales == Decimal("20000.00")
    assert arqueo.esperado == Decimal("58000.00")  # 50000 - 12000 + 20000


async def test_un_movimiento_con_monto_negativo_se_rechaza(dos_tenants):
    """El signo lo pone el tipo; aceptar negativos permitiría un egreso que suma."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia, turno = await _turno(session, a)
        with pytest.raises(ValueError):
            await registrar_movimiento(
                session, tenant=tenant, turno=turno, tipo=TipoMovimiento.EGRESO,
                concepto="Truco", monto=Decimal("-5000"), membership_id=membresia.id,
            )


# ── Cobros sin turno ─────────────────────────────────────────────────────

async def test_cobrar_sin_turno_no_se_bloquea_pero_queda_señalado(dos_tenants):
    """No se deja tirado al operario, pero el hueco se ve."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia = await _ctx(session, a)
        _, pago, _ = await _cobrar(session, tenant, a, membresia, placa="SIN001")
        assert pago.cash_shift_id is None

        # Ahora abre turno y consulta: el cobro anterior aparece como huérfano.
        sede = await session.get(ParkingLot, a.sede_asignada)
        turno = await abrir_turno(
            session, tenant=tenant, sede=sede, membership_id=membresia.id,
            base_inicial=Decimal("0"), ahora=ENTRADA - timedelta(hours=1),
        )
        arqueo = await calcular_arqueo(session, turno=turno)

    assert arqueo.efectivo_sin_turno == Decimal("9000.00")
    assert arqueo.esperado == Decimal("0.00"), "un cobro sin turno no puede alterar el esperado"


async def test_el_cobro_se_ata_al_turno_abierto(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia, turno = await _turno(session, a)
        _, pago, _ = await _cobrar(session, tenant, a, membresia)

    assert pago.cash_shift_id == turno.id


# ── Cierre ───────────────────────────────────────────────────────────────

async def test_el_cierre_calcula_la_diferencia(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia, turno = await _turno(session, a)
        await _cobrar(session, tenant, a, membresia)
        arqueo = await cerrar_turno(
            session, turno=turno, contado=Decimal("58500.00"), ahora=DOS_HORAS,
            notas="Falta un billete",
        )

    assert arqueo.esperado == Decimal("59000.00")
    assert arqueo.diferencia == Decimal("-500.00")
    assert not arqueo.cuadra


async def test_un_turno_que_cuadra(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia, turno = await _turno(session, a)
        await _cobrar(session, tenant, a, membresia)
        arqueo = await cerrar_turno(
            session, turno=turno, contado=Decimal("59000.00"), ahora=DOS_HORAS
        )
    assert arqueo.cuadra and arqueo.diferencia == Decimal("0.00")


async def test_el_esperado_queda_congelado_al_cerrar(dos_tenants):
    """Si se recalculara, un cambio posterior descuadraría un turno ya cuadrado."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia, turno = await _turno(session, a)
        _, pago, _ = await _cobrar(session, tenant, a, membresia)
        await cerrar_turno(session, turno=turno, contado=Decimal("59000.00"), ahora=DOS_HORAS)

        # Alguien toca el pago después de cerrar.
        pago.monto = Decimal("999999.00")
        await session.flush()
        await session.refresh(turno)

    assert turno.esperado == Decimal("59000.00")
    assert turno.diferencia == Decimal("0.00")


async def test_un_turno_cerrado_no_se_cierra_otra_vez(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        _, _, _, turno = await _turno(session, a)
        await cerrar_turno(session, turno=turno, contado=Decimal("50000"), ahora=DOS_HORAS)
        with pytest.raises(TurnoNoOperable):
            await cerrar_turno(session, turno=turno, contado=Decimal("50000"), ahora=DOS_HORAS)


async def test_un_turno_cerrado_no_admite_movimientos(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia, turno = await _turno(session, a)
        await cerrar_turno(session, turno=turno, contado=Decimal("50000"), ahora=DOS_HORAS)
        with pytest.raises(TurnoNoOperable):
            await registrar_movimiento(
                session, tenant=tenant, turno=turno, tipo=TipoMovimiento.EGRESO,
                concepto="Tarde", monto=Decimal("1000"), membership_id=membresia.id,
            )


# ── Aislamiento ──────────────────────────────────────────────────────────

async def test_los_turnos_no_se_ven_entre_tenants(dos_tenants):
    a, b = dos_tenants
    async with tenant_scope(a.id) as session:
        _, _, _, turno_a = await _turno(session, a)

    async with tenant_scope(b.id) as session:
        assert await session.get(CashShift, turno_a.id) is None
        assert list((await session.scalars(select(CashShift))).all()) == []


async def test_el_arqueo_de_un_tenant_no_cuenta_pagos_de_otro(dos_tenants):
    a, b = dos_tenants
    async with tenant_scope(b.id) as session:
        tenant_b, _, membresia_b, _ = await _turno(session, b)
        await _cobrar(session, tenant_b, b, membresia_b, placa="BBB999")

    async with tenant_scope(a.id) as session:
        _, _, _, turno_a = await _turno(session, a)
        arqueo = await calcular_arqueo(session, turno=turno_a)

    assert arqueo.esperado == Decimal("50000.00")
    assert arqueo.tickets_cobrados == 0
    assert arqueo.efectivo_sin_turno == Decimal("0.00")


async def test_turno_abierto_de_solo_encuentra_el_propio(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        _, sede, membresia, turno = await _turno(session, a)
        encontrado = await turno_abierto_de(
            session, parking_lot_id=sede.id, membership_id=membresia.id
        )
        assert encontrado.id == turno.id

        otra_sede = await session.get(ParkingLot, a.sede_ajena)
        assert await turno_abierto_de(
            session, parking_lot_id=otra_sede.id, membership_id=membresia.id
        ) is None
