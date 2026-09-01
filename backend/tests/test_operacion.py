"""Operación: ingreso, cotización, cobro y anulación.

Los importes se verifican llamando al servicio con un instante fijo. Por la
API se comprueban los códigos de estado y el comportamiento —idempotencia,
permisos, alcance—, no cifras que dependan del reloj.
"""

import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from decimal import Decimal as _D

import pytest
from sqlalchemy import select

from app.db.session import tenant_scope
from app.models.catalogo import ServiceItem, VehicleType
from app.models.parking_lot import ParkingLot
from app.models.tarifa import RatePlan, RateRule
from app.models.tarifa import RateRule as _RateRule
from app.models.tenant import Tenant
from app.models.ticket import EstadoTicket, MetodoPago, Payment, Ticket
from app.models.user import Membership
from app.services.tickets import (
    MotivoRequerido,
    OpcionDesconocida,
    PagoInsuficiente,
    PlacaConTicketAbierto,
    PlacaInvalida,
    TicketNoOperable,
    abrir_ticket,
    agregar_item,
    anular_ticket,
    buscar_tickets,
    cerrar_ticket,
    cotizar_ticket,
    normalizar_placa,
    opciones_de_cobro,
)

# Un lunes a las 8 de la mañana en Bogotá: dentro de la franja diurna.
ENTRADA = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)


async def _contexto(session, t, codigo_tipo="carro"):
    tenant = await session.get(Tenant, t.id)
    sede = await session.get(ParkingLot, t.sede_asignada)
    tipo = await session.scalar(
        select(VehicleType).where(VehicleType.codigo == codigo_tipo)
    )
    return tenant, sede, tipo


async def _abrir(session, t, *, placa="ABC123", tipo="carro", entrada=ENTRADA, **extra):
    tenant, sede, tipo_obj = await _contexto(session, t, tipo)
    return await abrir_ticket(
        session, tenant=tenant, sede=sede, tipo=tipo_obj, placa=placa,
        entrada=entrada, membership_id=None, **extra,
    )


# ── Placas ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("entrada", "esperado"),
    [
        ("abc123", "ABC123"),
        ("ABC-123", "ABC123"),
        ("abc 123", "ABC123"),
        ("  a b c 1 2 3 ", "ABC123"),
        ("", None),
        (None, None),
    ],
)
def test_la_placa_se_normaliza(entrada, esperado):
    """'abc-123' y 'ABC 123' son el mismo vehículo."""
    assert normalizar_placa(entrada) == esperado


async def test_un_carro_necesita_placa(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        with pytest.raises(PlacaInvalida):
            await _abrir(session, a, placa=None)


async def test_una_bicicleta_no_necesita_placa(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        ticket = await _abrir(session, a, placa=None, tipo="bicicleta")
    assert ticket.placa is None
    assert ticket.estado is EstadoTicket.ABIERTO


# ── Apertura ─────────────────────────────────────────────────────────────

async def test_el_ticket_lleva_consecutivo_de_la_sede(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        primero = await _abrir(session, a, placa="AAA111")
        segundo = await _abrir(session, a, placa="BBB222")

    assert primero.numero == 1
    assert segundo.numero == 2
    assert primero.codigo == "S1-000001"
    assert segundo.codigo == "S1-000002"


async def test_dos_ingresos_simultaneos_no_repiten_consecutivo(dos_tenants):
    """El UPDATE ... RETURNING serializa: el segundo espera al primero."""
    a, _ = dos_tenants

    async def ingresar(placa: str) -> int:
        async with tenant_scope(a.id) as session:
            ticket = await _abrir(session, a, placa=placa)
            return ticket.numero

    numeros = await asyncio.gather(ingresar("CCC111"), ingresar("DDD222"))
    assert sorted(numeros) == [1, 2], f"consecutivos repetidos: {numeros}"


async def test_el_ticket_congela_las_reglas_al_abrir(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        ticket = await _abrir(session, a)

    assert ticket.rate_snapshot["plan_codigo"] == "general"
    assert ticket.rate_snapshot["plan_version"] == 1
    codigos = {r["codigo"] for r in ticket.rate_snapshot["reglas"]}
    assert codigos == {"carro-general", "carro-nocturna"}


async def test_la_placa_repetida_advierte_con_el_ticket_existente(dos_tenants):
    """D6: se advierte, no se bloquea."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        primero = await _abrir(session, a, placa="ABC123")

        with pytest.raises(PlacaConTicketAbierto) as aviso:
            await _abrir(session, a, placa="abc 123")

    assert aviso.value.ticket.codigo == primero.codigo


async def test_forzando_se_puede_abrir_la_misma_placa(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        await _abrir(session, a, placa="ABC123")
        segundo = await _abrir(session, a, placa="ABC123", forzar=True)
    assert segundo.numero == 2


async def test_una_placa_cerrada_no_estorba_al_siguiente_ingreso(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        primero = await _abrir(session, a, placa="ABC123")
        await cerrar_ticket(
            session, tenant=tenant, ticket_id=primero.id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(hours=2), membership_id=None,
        )
        segundo = await _abrir(session, a, placa="ABC123", entrada=ENTRADA + timedelta(hours=3))
    assert segundo.estado is EstadoTicket.ABIERTO


# ── Cotización ───────────────────────────────────────────────────────────

async def test_cotizar_no_cierra_el_ticket(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        c = await cotizar_ticket(
            session, tenant=tenant, ticket=ticket, ahora=ENTRADA + timedelta(minutes=137)
        )
        assert ticket.estado is EstadoTicket.ABIERTO
        assert ticket.salida_at is None

    assert c.total == Decimal("9000.00")  # tres fracciones de hora diurna


async def test_la_cortesia_aplica_al_salir_enseguida(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        c = await cotizar_ticket(
            session, tenant=tenant, ticket=ticket, ahora=ENTRADA + timedelta(minutes=10)
        )
    assert c.en_cortesia and c.total == Decimal("0.00")


# ── Artículos ────────────────────────────────────────────────────────────

async def test_el_articulo_congela_su_precio(dos_tenants):
    """Subir el precio del casco no debe recalcular los ya entregados."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        casco = await session.scalar(select(ServiceItem).where(ServiceItem.codigo == "casco"))
        await agregar_item(session, tenant=tenant, ticket=ticket, articulo=casco)

        # El administrador sube el precio con el ticket abierto.
        casco.precio = Decimal("5000.00")
        await session.flush()

        c = await cotizar_ticket(
            session, tenant=tenant, ticket=ticket, ahora=ENTRADA + timedelta(hours=1)
        )

    # 3000 de la hora + el casco al precio que tenía cuando se entregó.
    assert c.total == Decimal("4000.00")


async def test_no_se_añaden_articulos_a_un_ticket_cerrado(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(hours=1), membership_id=None,
        )
        await session.refresh(ticket)
        casco = await session.scalar(select(ServiceItem).where(ServiceItem.codigo == "casco"))

        with pytest.raises(TicketNoOperable):
            await agregar_item(session, tenant=tenant, ticket=ticket, articulo=casco)


# ── Cobro ────────────────────────────────────────────────────────────────

async def test_cobrar_cierra_el_ticket_y_guarda_el_desglose(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        salida = ENTRADA + timedelta(minutes=137)

        ticket, pago, reintento = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=salida, membership_id=None, recibido=Decimal("10000.00"),
        )
        await session.refresh(ticket)
        cargos = [(c.concepto, c.monto) for c in ticket.cargos]

    assert not reintento
    assert ticket.estado is EstadoTicket.CERRADO
    assert ticket.salida_at == salida
    assert pago.monto == Decimal("9000.00")
    assert pago.cambio == Decimal("1000.00")
    assert cargos and sum(m for _, m in cargos) == pago.monto


async def test_el_recibo_guardado_se_puede_reproducir_tal_cual(dos_tenants):
    """El desglose queda en la base: no depende de recalcular años después."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(minutes=137), membership_id=None,
        )
        # Se cambia la tarifa después de cobrar.
        regla = await session.scalar(
            select(RateRule).where(RateRule.codigo == "carro-general")
        )
        regla.precio_bloque = Decimal("99000.00")
        await session.flush()

        await session.refresh(ticket)
        guardado = sum(c.monto for c in ticket.cargos)

    assert guardado == Decimal("9000.00")


async def test_no_se_cobra_menos_de_lo_que_vale(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        with pytest.raises(PagoInsuficiente):
            await cerrar_ticket(
                session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
                ahora=ENTRADA + timedelta(hours=3), membership_id=None,
                recibido=Decimal("1000.00"),
            )


async def test_una_salida_en_cortesia_se_registra_como_cortesia(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        _, pago, _ = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(minutes=5), membership_id=None,
        )
    assert pago.monto == Decimal("0.00")
    assert pago.metodo is MetodoPago.CORTESIA


async def test_reintentar_el_cobro_no_cobra_dos_veces(dos_tenants):
    """El caso real: el operario no ve la respuesta y vuelve a pulsar."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        salida = ENTRADA + timedelta(minutes=137)

        _, primero, r1 = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=salida, membership_id=None,
        )
        _, segundo, r2 = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=salida + timedelta(hours=5), membership_id=None,
        )
        pagos = list((await session.scalars(
            select(Payment).where(Payment.ticket_id == ticket.id)
        )).all())

    assert r1 is False and r2 is True
    assert primero.id == segundo.id
    assert len(pagos) == 1
    assert segundo.monto == Decimal("9000.00"), "el reintento recalculó con más tiempo"


# ── Anulación ────────────────────────────────────────────────────────────

async def test_anular_un_ticket_abierto(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        ticket = await _abrir(session, a)
        ticket = await anular_ticket(
            session, ticket_id=ticket.id, motivo="Placa mal digitada", membership_id=None
        )
    assert ticket.estado is EstadoTicket.ANULADO
    assert ticket.anulacion_motivo == "Placa mal digitada"


async def test_un_ticket_cobrado_no_se_anula(dos_tenants):
    """Anular algo ya cobrado escondería dinero: eso es una devolución."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(hours=1), membership_id=None,
        )
        with pytest.raises(TicketNoOperable, match="devolución"):
            await anular_ticket(session, ticket_id=ticket.id, motivo="x", membership_id=None)


async def test_un_ticket_anulado_no_se_cobra(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        await anular_ticket(session, ticket_id=ticket.id, motivo="x", membership_id=None)
        with pytest.raises(TicketNoOperable):
            await cerrar_ticket(
                session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
                ahora=ENTRADA + timedelta(hours=1), membership_id=None,
            )


# ── Búsqueda ─────────────────────────────────────────────────────────────

async def test_buscar_por_los_ultimos_digitos_de_la_placa(dos_tenants):
    """En la caseta se teclean tres dígitos, no la placa entera."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        await _abrir(session, a, placa="ABC123")
        await _abrir(session, a, placa="XYZ789")

        encontrados = await buscar_tickets(session, sedes=None, placa="123")
        assert [t.placa for t in encontrados] == ["ABC123"]

        por_codigo = await buscar_tickets(session, sedes=None, placa="S1-000002")
        assert [t.placa for t in por_codigo] == ["XYZ789"]


async def test_la_busqueda_respeta_el_alcance_por_sede(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, tipo = await _contexto(session, a)
        ajena = await session.get(ParkingLot, a.sede_ajena)
        await _abrir(session, a, placa="AAA111")
        await abrir_ticket(
            session, tenant=tenant, sede=ajena, tipo=tipo, placa="BBB222",
            entrada=ENTRADA, membership_id=None,
        )

        solo_suya = await buscar_tickets(session, sedes=frozenset({a.sede_asignada}))
        todas = await buscar_tickets(session, sedes=None)

    assert {t.placa for t in solo_suya} == {"AAA111"}
    assert {t.placa for t in todas} == {"AAA111", "BBB222"}


# ── Aislamiento ──────────────────────────────────────────────────────────

async def test_los_tickets_de_un_tenant_no_se_ven_desde_otro(dos_tenants):
    a, b = dos_tenants
    async with tenant_scope(a.id) as session:
        ticket_de_a = await _abrir(session, a, placa="AAA111")

    async with tenant_scope(b.id) as session:
        assert await session.get(Ticket, ticket_de_a.id) is None
        assert await buscar_tickets(session, sedes=None) == []


async def test_el_consecutivo_es_independiente_por_tenant(dos_tenants):
    a, b = dos_tenants
    async with tenant_scope(a.id) as session:
        de_a = await _abrir(session, a, placa="AAA111")
    async with tenant_scope(b.id) as session:
        de_b = await _abrir(session, b, placa="BBB222")

    assert de_a.numero == 1 and de_b.numero == 1
    assert de_a.id != de_b.id


# ── Opciones de cobro y ajuste manual ────────────────────────────────────
# Un parqueadero no cobra siempre igual: al mismo carro se le puede aplicar
# la tarifa por hora, una plena o un convenio, y quien cobra elige con el
# cliente delante.




async def _con_opcion_plena(session, t, precio="12000.00"):
    """Añade una tarifa plena al plan activo, como haría el administrador."""
    plan = await session.scalar(select(RatePlan).where(RatePlan.codigo == "general"))
    tipo = await session.scalar(select(VehicleType).where(VehicleType.codigo == "carro"))
    session.add(
        _RateRule(
            tenant_id=t.id, rate_plan_id=plan.id, vehicle_type_id=tipo.id,
            codigo="carro-plena", nombre="Todo el día",
            modo="plena", precio_plena=_D(precio),
        )
    )
    await session.flush()


async def test_se_ofrecen_todas_las_formas_de_cobro(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        await _con_opcion_plena(session, a)
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        opciones = await opciones_de_cobro(
            session, tenant=tenant, ticket=ticket, ahora=ENTRADA + timedelta(minutes=137)
        )

    nombres = {o.nombre for o in opciones}
    assert "Todo el día" in nombres, "la tarifa plena debería ofrecerse"
    assert sum(1 for o in opciones if o.recomendada) == 1, "solo una recomendada"
    assert opciones[0].recomendada, "la recomendada va primero"
    # La automática cobra tres horas; la plena, su precio único.
    por_nombre = {o.nombre: o.cotizacion.total for o in opciones}
    assert por_nombre["Todo el día"] == _D("12000.00")


async def test_el_operario_elige_una_opcion_distinta(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        await _con_opcion_plena(session, a)
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)

        _, pago, _ = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(minutes=137), membership_id=None,
            opcion="carro-plena",
        )

    assert pago.monto == _D("12000.00")
    assert pago.regla_aplicada == "carro-plena"
    assert pago.ajuste_manual is False


async def test_una_opcion_inexistente_se_rechaza(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        with pytest.raises(OpcionDesconocida):
            await cerrar_ticket(
                session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
                ahora=ENTRADA + timedelta(hours=2), membership_id=None,
                opcion="tarifa-inventada",
            )


async def test_un_monto_a_mano_exige_motivo(dos_tenants):
    """Sin explicación no hay nada que auditar después."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        with pytest.raises(MotivoRequerido):
            await cerrar_ticket(
                session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
                ahora=ENTRADA + timedelta(minutes=137), membership_id=None,
                monto_manual=_D("5000.00"),
            )


async def test_el_monto_a_mano_guarda_lo_que_el_sistema_habia_calculado(dos_tenants):
    """Sin ese dato, un ajuste sería indistinguible de un cobro normal."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        _, pago, _ = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(minutes=137), membership_id=None,
            monto_manual=_D("5000.00"), motivo_ajuste="Cliente frecuente",
        )

    assert pago.monto == _D("5000.00")
    assert pago.monto_calculado == _D("9000.00")
    assert pago.ajuste_manual is True
    assert pago.motivo_ajuste == "Cliente frecuente"


async def test_el_desglose_sigue_sumando_el_total_con_ajuste(dos_tenants):
    """Un recibo que no cuadra no sirve de nada."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        ticket_id = ticket.id
        await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket_id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(minutes=137), membership_id=None,
            monto_manual=_D("5000.00"), motivo_ajuste="Descuento acordado",
        )
        await session.refresh(ticket)
        cargos = [(c.concepto, c.monto) for c in ticket.cargos]

    assert sum(m for _, m in cargos) == _D("5000.00")
    assert any("Ajuste manual" in c for c, _ in cargos)


async def test_cobrar_de_mas_tambien_se_registra_como_ajuste(dos_tenants):
    """El ticket perdido se cobra por encima de la tarifa, y debe verse."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        _, pago, _ = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(minutes=137), membership_id=None,
            monto_manual=_D("24000.00"), motivo_ajuste="Ticket perdido",
        )

    assert pago.monto == _D("24000.00")
    assert pago.monto_calculado == _D("9000.00")
    assert pago.ajuste_manual is True


async def test_sin_elegir_nada_se_cobra_la_recomendada(dos_tenants):
    """Lo de siempre tiene que seguir funcionando igual."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        _, pago, _ = await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(minutes=137), membership_id=None,
        )

    assert pago.monto == _D("9000.00")
    assert pago.ajuste_manual is False
    assert pago.monto_calculado == _D("9000.00")


async def test_el_ajuste_manual_entra_completo_en_el_arqueo(dos_tenants):
    """La caja tiene que cuadrar con lo que de verdad entró al cajón."""
    from app.services.caja import abrir_turno, calcular_arqueo

    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, sede, _ = await _contexto(session, a)
        membresia = await session.scalar(
            select(Membership).where(Membership.tenant_id == a.id).limit(1)
        )
        turno = await abrir_turno(
            session, tenant=tenant, sede=sede, membership_id=membresia.id,
            base_inicial=_D("0"), ahora=ENTRADA,
        )
        ticket = await _abrir(session, a)
        await cerrar_ticket(
            session, tenant=tenant, ticket_id=ticket.id, metodo=MetodoPago.EFECTIVO,
            ahora=ENTRADA + timedelta(minutes=137), membership_id=membresia.id,
            monto_manual=_D("5000.00"), motivo_ajuste="Descuento",
        )
        arqueo = await calcular_arqueo(session, turno=turno)

    assert arqueo.efectivo_cobrado == _D("5000.00"), \
        "el arqueo debe contar lo cobrado, no lo calculado"


async def test_las_tarifas_por_franja_no_se_ofrecen_como_opcion(dos_tenants):
    """La nocturna no es una elección de quien cobra: la aplica sola la
    automática. Ofrecerla suelta mostraría dos opciones idénticas."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        opciones = await opciones_de_cobro(
            session, tenant=tenant, ticket=ticket, ahora=ENTRADA + timedelta(minutes=137)
        )

    # El plan de prueba tiene carro-general y carro-nocturna: una sola opción.
    assert len(opciones) == 1
    assert opciones[0].recomendada


async def test_no_se_repiten_opciones_indistinguibles(dos_tenants):
    """Dos opciones con el mismo nombre y el mismo precio son una pregunta
    sin respuesta para quien cobra."""
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        await _con_opcion_plena(session, a, precio="12000.00")
        await _con_opcion_plena_extra(session, a, precio="12000.00")
        tenant, _, _ = await _contexto(session, a)
        ticket = await _abrir(session, a)
        opciones = await opciones_de_cobro(
            session, tenant=tenant, ticket=ticket, ahora=ENTRADA + timedelta(minutes=137)
        )

    etiquetas = [(o.nombre, o.cotizacion.total) for o in opciones]
    assert len(etiquetas) == len(set(etiquetas)), f"opciones repetidas: {etiquetas}"


async def _con_opcion_plena_extra(session, t, precio):
    """Otra plena con el mismo nombre y precio, para probar el deduplicado."""
    plan = await session.scalar(select(RatePlan).where(RatePlan.codigo == "general"))
    tipo = await session.scalar(select(VehicleType).where(VehicleType.codigo == "carro"))
    session.add(
        _RateRule(
            tenant_id=t.id, rate_plan_id=plan.id, vehicle_type_id=tipo.id,
            codigo="carro-plena-2", nombre="Todo el día",
            modo="plena", precio_plena=_D(precio),
        )
    )
    await session.flush()
