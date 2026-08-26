"""Reportes de ocupación e ingresos, y la API de caja."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.session import tenant_scope
from app.models.catalogo import VehicleType
from app.models.parking_lot import ParkingLot
from app.models.tenant import Tenant
from app.models.ticket import MetodoPago
from app.models.user import Membership
from app.services.reportes import ingresos, ingresos_a_csv, ocupacion
from app.services.tickets import abrir_ticket, cerrar_ticket

from .conftest import cabecera, entrar

BOGOTA = "America/Bogota"
# 2026-08-24 08:00 en Bogotá.
DIA_1 = datetime(2026, 8, 24, 13, 0, tzinfo=UTC)
DIA_2 = DIA_1 + timedelta(days=1)


async def _ctx(session, t):
    tenant = await session.get(Tenant, t.id)
    sede = await session.get(ParkingLot, t.sede_asignada)
    membresia = await session.scalar(
        select(Membership).where(Membership.tenant_id == t.id).limit(1)
    )
    return tenant, sede, membresia


async def _ticket_cobrado(session, t, *, placa, tipo="carro", entrada, salida, metodo):
    tenant, sede, membresia = await _ctx(session, t)
    tipo_obj = await session.scalar(select(VehicleType).where(VehicleType.codigo == tipo))
    ticket = await abrir_ticket(
        session, tenant=tenant, sede=sede, tipo=tipo_obj, placa=placa,
        entrada=entrada, membership_id=membresia.id,
    )
    return await cerrar_ticket(
        session, tenant=tenant, ticket_id=ticket.id, metodo=metodo,
        ahora=salida, membership_id=membresia.id,
    )


# ── Ocupación ────────────────────────────────────────────────────────────

async def test_la_ocupacion_cuenta_lo_que_hay_adentro(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, sede, membresia = await _ctx(session, a)
        carro = await session.scalar(select(VehicleType).where(VehicleType.codigo == "carro"))
        moto = await session.scalar(select(VehicleType).where(VehicleType.codigo == "moto"))

        for placa, tipo in [("AAA111", carro), ("BBB222", carro), ("CCC333", moto)]:
            await abrir_ticket(
                session, tenant=tenant, sede=sede, tipo=tipo, placa=placa,
                entrada=DIA_1, membership_id=membresia.id,
            )

        filas = await ocupacion(session, sedes=None)

    por_tipo = {f.tipo: f.adentro for f in filas}
    assert por_tipo == {"Carro": 2, "Moto": 1}


async def test_un_ticket_cobrado_deja_de_ocupar(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        await _ticket_cobrado(
            session, a, placa="AAA111", entrada=DIA_1,
            salida=DIA_1 + timedelta(hours=2), metodo=MetodoPago.EFECTIVO,
        )
        filas = await ocupacion(session, sedes=None)
    assert filas == []


async def test_la_ocupacion_respeta_el_alcance_por_sede(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        tenant, _, membresia = await _ctx(session, a)
        carro = await session.scalar(select(VehicleType).where(VehicleType.codigo == "carro"))
        ajena = await session.get(ParkingLot, a.sede_ajena)
        await abrir_ticket(
            session, tenant=tenant, sede=ajena, tipo=carro, placa="ZZZ999",
            entrada=DIA_1, membership_id=membresia.id,
        )
        propias = await ocupacion(session, sedes=frozenset({a.sede_asignada}))
        todas = await ocupacion(session, sedes=None)

    assert propias == []
    assert sum(f.adentro for f in todas) == 1


# ── Ingresos ─────────────────────────────────────────────────────────────

async def test_los_ingresos_se_agrupan_por_dia_metodo_y_tipo(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        # Día 1: dos carros, uno en efectivo y otro con tarjeta.
        await _ticket_cobrado(session, a, placa="AAA111", entrada=DIA_1,
                              salida=DIA_1 + timedelta(minutes=137),
                              metodo=MetodoPago.EFECTIVO)
        await _ticket_cobrado(session, a, placa="BBB222", entrada=DIA_1,
                              salida=DIA_1 + timedelta(minutes=137),
                              metodo=MetodoPago.TARJETA)
        # Día 2: una moto.
        await _ticket_cobrado(session, a, placa="CCC333", tipo="moto", entrada=DIA_2,
                              salida=DIA_2 + timedelta(minutes=65),
                              metodo=MetodoPago.EFECTIVO)

        datos = await ingresos(
            session, sedes=None, desde=DIA_1.date(), hasta=DIA_2.date(), zona=BOGOTA
        )

    assert datos.tickets == 3
    assert [f.dia.isoformat() for f in datos.por_dia] == ["2026-08-24", "2026-08-25"]
    assert {f.concepto for f in datos.por_metodo} == {"efectivo", "tarjeta"}

    por_tipo = {f.concepto: f.total for f in datos.por_tipo}
    assert por_tipo["Carro"] == Decimal("18000.00")  # dos carros a 9.000
    assert por_tipo["Moto"] == Decimal("2700.00")  # tres fracciones de media hora
    assert datos.total == Decimal("20700.00")


async def test_un_ticket_fuera_del_rango_no_cuenta(dos_tenants):
    a, _ = dos_tenants
    async with tenant_scope(a.id) as session:
        await _ticket_cobrado(session, a, placa="AAA111", entrada=DIA_1,
                              salida=DIA_1 + timedelta(hours=2), metodo=MetodoPago.EFECTIVO)
        datos = await ingresos(
            session, sedes=None, desde=DIA_2.date(), hasta=DIA_2.date(), zona=BOGOTA
        )
    assert datos.tickets == 0 and datos.total == Decimal("0.00")


async def test_el_dia_se_agrupa_en_la_hora_de_la_sede(dos_tenants):
    """Una salida a las 02:00 UTC es todavía del día anterior en Bogotá."""
    a, _ = dos_tenants
    salida = datetime(2026, 8, 26, 2, 0, tzinfo=UTC)  # 25 de agosto, 21:00 en Bogotá
    async with tenant_scope(a.id) as session:
        await _ticket_cobrado(
            session, a, placa="AAA111", entrada=salida - timedelta(hours=2),
            salida=salida, metodo=MetodoPago.EFECTIVO,
        )
        datos = await ingresos(
            session, sedes=None, desde=salida.date() - timedelta(days=2),
            hasta=salida.date(), zona=BOGOTA,
        )

    assert [f.dia.isoformat() for f in datos.por_dia] == ["2026-08-25"]


async def test_los_ingresos_de_otro_tenant_no_se_suman(dos_tenants):
    a, b = dos_tenants
    async with tenant_scope(b.id) as session:
        await _ticket_cobrado(session, b, placa="BBB999", entrada=DIA_1,
                              salida=DIA_1 + timedelta(hours=5), metodo=MetodoPago.EFECTIVO)

    async with tenant_scope(a.id) as session:
        datos = await ingresos(
            session, sedes=None, desde=DIA_1.date(), hasta=DIA_2.date(), zona=BOGOTA
        )
    assert datos.tickets == 0


def test_el_csv_lleva_encabezado_y_totales():
    from app.services.reportes import FilaConcepto, FilaDia, Ingresos

    datos = Ingresos(
        desde=DIA_1.date(), hasta=DIA_2.date(), total=Decimal("20700.00"), tickets=3,
        por_dia=[FilaDia(DIA_1.date(), 2, Decimal("18000.00"))],
        por_metodo=[FilaConcepto("efectivo", 2, Decimal("11700.00"))],
        por_tipo=[FilaConcepto("Carro", 2, Decimal("18000.00"))],
    )
    csv = ingresos_a_csv(datos)
    lineas = csv.strip().split("\n")

    assert lineas[0] == "seccion,concepto,tickets,total"
    assert lineas[1] == "dia,2026-08-24,2,18000.00"
    assert lineas[-1] == "total,,3,20700.00"


# ── API ──────────────────────────────────────────────────────────────────

async def _cab(client, t, quien="operario"):
    return cabecera(await entrar(client, t.slug, t.operario if quien == "operario" else t.admin))


async def test_el_operario_abre_y_cierra_su_turno(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a)

    abierto = await client.post(
        f"/api/v1/t/{a.slug}/caja/abrir", headers=cab,
        json={"parking_lot_id": str(a.sede_asignada), "base_inicial": "50000"},
    )
    assert abierto.status_code == 201
    turno = abierto.json()["turno"]

    segundo = await client.post(
        f"/api/v1/t/{a.slug}/caja/abrir", headers=cab,
        json={"parking_lot_id": str(a.sede_asignada), "base_inicial": "1000"},
    )
    assert segundo.status_code == 409

    cerrado = await client.post(
        f"/api/v1/t/{a.slug}/caja/{turno['id']}/cerrar", headers=cab,
        json={"contado": "49500", "notas": "Faltaron 500"},
    )
    assert cerrado.status_code == 200
    arqueo = cerrado.json()["arqueo"]
    assert Decimal(arqueo["esperado"]) == Decimal("50000.00")
    assert Decimal(arqueo["diferencia"]) == Decimal("-500.00")
    assert arqueo["cuadra"] is False


async def test_mi_turno_devuelve_null_sin_turno_abierto(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.get(
        f"/api/v1/t/{a.slug}/caja/mi-turno?parking_lot_id={a.sede_asignada}",
        headers=await _cab(client, a),
    )
    assert r.status_code == 200
    assert r.json() is None


async def test_los_descuadres_salen_ordenados(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a)
    turno = (await client.post(
        f"/api/v1/t/{a.slug}/caja/abrir", headers=cab,
        json={"parking_lot_id": str(a.sede_asignada), "base_inicial": "50000"},
    )).json()["turno"]
    await client.post(
        f"/api/v1/t/{a.slug}/caja/{turno['id']}/cerrar", headers=cab,
        json={"contado": "48000"},
    )

    r = await client.get(
        f"/api/v1/t/{a.slug}/caja/descuadres", headers=await _cab(client, a, "admin")
    )
    assert r.status_code == 200
    assert Decimal(r.json()[0]["diferencia"]) == Decimal("-2000.00")


async def test_al_operario_le_falta_permiso_para_ver_reportes(dos_tenants, client):
    """El operario opera su caja; los reportes son del supervisor."""
    a, _ = dos_tenants
    r = await client.get(f"/api/v1/t/{a.slug}/reportes/ingresos", headers=await _cab(client, a))
    assert r.status_code == 403
    assert "report:read" in r.json()["detail"]


async def test_el_admin_ve_los_reportes(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a, "admin")

    ocupacion_res = await client.get(f"/api/v1/t/{a.slug}/reportes/ocupacion", headers=cab)
    assert ocupacion_res.status_code == 200
    assert "total" in ocupacion_res.json()

    ingresos_res = await client.get(f"/api/v1/t/{a.slug}/reportes/ingresos", headers=cab)
    assert ingresos_res.status_code == 200
    assert {"desde", "hasta", "total", "por_dia"} <= ingresos_res.json().keys()


async def test_el_csv_se_descarga_con_nombre(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.get(
        f"/api/v1/t/{a.slug}/reportes/ingresos.csv", headers=await _cab(client, a, "admin")
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    assert "attachment" in r.headers["content-disposition"]
    assert r.text.startswith("seccion,concepto,tickets,total")


async def test_un_rango_invertido_se_rechaza(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.get(
        f"/api/v1/t/{a.slug}/reportes/ingresos?desde=2026-08-30&hasta=2026-08-01",
        headers=await _cab(client, a, "admin"),
    )
    assert r.status_code == 400


async def test_un_rango_enorme_se_rechaza(dos_tenants, client):
    """Sin tope, una consulta de diez años tumbaría la base."""
    a, _ = dos_tenants
    r = await client.get(
        f"/api/v1/t/{a.slug}/reportes/ingresos?desde=2000-01-01&hasta=2026-12-31",
        headers=await _cab(client, a, "admin"),
    )
    assert r.status_code == 400


async def test_no_se_ve_el_turno_de_otro_tenant(dos_tenants, client):
    a, b = dos_tenants
    turno_b = (await client.post(
        f"/api/v1/t/{b.slug}/caja/abrir", headers=await _cab(client, b),
        json={"parking_lot_id": str(b.sede_asignada), "base_inicial": "10000"},
    )).json()["turno"]

    r = await client.get(
        f"/api/v1/t/{a.slug}/caja/turnos/{turno_b['id']}",
        headers=await _cab(client, a, "admin"),
    )
    assert r.status_code == 404
