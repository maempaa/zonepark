"""API de operación.

Aquí se verifica comportamiento —códigos de estado, idempotencia,
permisos, alcance—, no importes: el reloj real los mueve. Los importes se
comprueban en `test_operacion.py` con un instante fijo.
"""

from sqlalchemy import func, select

from app.db.session import tenant_scope
from app.models.ticket import Payment, Ticket

from .conftest import cabecera, entrar


async def _cab(client, t, quien="operario"):
    email = t.operario if quien == "operario" else t.admin
    return cabecera(await entrar(client, t.slug, email))


async def _ingresar(client, t, cab, *, placa="ABC123", tipo="carro", **extra):
    return await client.post(
        f"/api/v1/t/{t.slug}/tickets",
        headers=cab,
        json={
            "parking_lot_id": str(t.sede_asignada),
            "vehicle_type_id": str(t.tipos[tipo]),
            "placa": placa,
            **extra,
        },
    )


# ── Ingreso ──────────────────────────────────────────────────────────────

async def test_registrar_un_ingreso(dos_tenants, client):
    a, _ = dos_tenants
    r = await _ingresar(client, a, await _cab(client, a))
    assert r.status_code == 201
    d = r.json()
    assert d["codigo"] == "S1-000001"
    assert d["placa"] == "ABC123"
    assert d["estado"] == "abierto"
    assert d["plan_codigo"] == "general"


async def test_la_placa_repetida_devuelve_409_con_el_ticket_abierto(dos_tenants, client):
    """D6: el operario necesita ver cuál es el ticket que ya existe."""
    a, _ = dos_tenants
    cab = await _cab(client, a)
    primero = (await _ingresar(client, a, cab)).json()

    r = await _ingresar(client, a, cab, placa="abc-123")
    assert r.status_code == 409
    detalle = r.json()["detail"]
    assert detalle["ticket_abierto"]["codigo"] == primero["codigo"]


async def test_forzar_permite_el_segundo_ingreso(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a)
    await _ingresar(client, a, cab)
    r = await _ingresar(client, a, cab, forzar=True)
    assert r.status_code == 201


async def test_un_carro_sin_placa_se_rechaza(dos_tenants, client):
    a, _ = dos_tenants
    r = await _ingresar(client, a, await _cab(client, a), placa=None)
    assert r.status_code == 400


async def test_una_bicicleta_entra_sin_placa(dos_tenants, client):
    a, _ = dos_tenants
    r = await _ingresar(client, a, await _cab(client, a), placa=None, tipo="bicicleta")
    assert r.status_code == 201


async def test_el_operario_no_registra_en_una_sede_ajena(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/tickets",
        headers=await _cab(client, a),
        json={"parking_lot_id": str(a.sede_ajena),
              "vehicle_type_id": str(a.tipos["carro"]), "placa": "ZZZ999"},
    )
    assert r.status_code == 403


# ── Búsqueda y cotización ────────────────────────────────────────────────

async def test_buscar_por_placa_parcial(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a)
    await _ingresar(client, a, cab, placa="ABC123")
    await _ingresar(client, a, cab, placa="XYZ789")

    r = await client.get(f"/api/v1/t/{a.slug}/tickets?placa=123", headers=cab)
    assert [t["placa"] for t in r.json()] == ["ABC123"]


async def test_cotizar_no_cierra_el_ticket(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a)
    ticket = (await _ingresar(client, a, cab)).json()

    r = await client.get(f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/cotizar", headers=cab)
    assert r.status_code == 200
    assert "total" in r.json()

    detalle = (await client.get(f"/api/v1/t/{a.slug}/tickets/{ticket['id']}", headers=cab)).json()
    assert detalle["estado"] == "abierto"
    assert detalle["salida_at"] is None


async def test_añadir_un_articulo(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a)
    ticket = (await _ingresar(client, a, cab)).json()

    r = await client.post(
        f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/items",
        headers=cab, json={"codigo": "casco", "cantidad": 2},
    )
    assert r.status_code == 200
    assert r.json()["items"][0]["cantidad"] == 2


# ── Cobro ────────────────────────────────────────────────────────────────

async def test_cobrar_devuelve_el_recibo(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a)
    ticket = (await _ingresar(client, a, cab)).json()

    r = await client.post(
        f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/cobrar",
        headers=cab, json={"metodo": "efectivo", "recibido": "50000"},
    )
    assert r.status_code == 201
    recibo = r.json()
    assert recibo["reintento"] is False
    assert recibo["ticket"]["estado"] == "cerrado"
    assert recibo["cotizacion"]["lineas"]


async def test_el_reintento_devuelve_el_mismo_recibo_y_no_cobra_dos_veces(dos_tenants, client):
    """El operario pulsa dos veces porque no vio la respuesta."""
    a, _ = dos_tenants
    cab = await _cab(client, a)
    ticket = (await _ingresar(client, a, cab)).json()
    ruta = f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/cobrar"
    cuerpo = {"metodo": "efectivo", "recibido": "50000"}

    primero = await client.post(ruta, headers={**cab, "Idempotency-Key": "abc-1"}, json=cuerpo)
    segundo = await client.post(ruta, headers={**cab, "Idempotency-Key": "abc-1"}, json=cuerpo)

    assert primero.status_code == 201
    assert segundo.status_code == 200
    assert segundo.json()["reintento"] is True
    assert primero.json()["pago"]["monto"] == segundo.json()["pago"]["monto"]

    async with tenant_scope(a.id) as session:
        cuantos = await session.scalar(
            select(func.count()).select_from(Payment).where(Payment.ticket_id == ticket["id"])
        )
    assert cuantos == 1


async def test_reintentar_sin_llave_tampoco_cobra_dos_veces(dos_tenants, client):
    """La idempotencia no depende de que el cliente mande la cabecera."""
    a, _ = dos_tenants
    cab = await _cab(client, a)
    ticket = (await _ingresar(client, a, cab)).json()
    ruta = f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/cobrar"

    await client.post(ruta, headers=cab, json={"metodo": "efectivo"})
    segundo = await client.post(ruta, headers=cab, json={"metodo": "efectivo"})

    assert segundo.status_code == 200
    assert segundo.json()["reintento"] is True

    async with tenant_scope(a.id) as session:
        cuantos = await session.scalar(
            select(func.count()).select_from(Payment).where(Payment.ticket_id == ticket["id"])
        )
    assert cuantos == 1


async def test_pagar_con_menos_de_lo_debido_se_rechaza(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a)
    ticket = (await _ingresar(client, a, cab)).json()
    # Se deja pasar tiempo simulado añadiendo un artículo caro.
    await client.post(
        f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/items",
        headers=cab, json={"codigo": "lavada"},
    )
    r = await client.post(
        f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/cobrar",
        headers=cab, json={"metodo": "efectivo", "recibido": "100"},
    )
    assert r.status_code == 400


# ── Permisos ─────────────────────────────────────────────────────────────

async def test_al_operario_le_falta_permiso_para_anular(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a)
    ticket = (await _ingresar(client, a, cab)).json()

    r = await client.post(
        f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/anular",
        headers=cab, json={"motivo": "me equivoqué"},
    )
    assert r.status_code == 403
    assert "ticket:void" in r.json()["detail"]


async def test_el_admin_anula(dos_tenants, client):
    a, _ = dos_tenants
    ticket = (await _ingresar(client, a, await _cab(client, a))).json()

    r = await client.post(
        f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/anular",
        headers=await _cab(client, a, "admin"),
        json={"motivo": "Placa mal digitada"},
    )
    assert r.status_code == 200
    assert r.json()["estado"] == "anulado"


async def test_un_ticket_anulado_no_se_cobra(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _cab(client, a)
    ticket = (await _ingresar(client, a, cab)).json()
    await client.post(
        f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/anular",
        headers=await _cab(client, a, "admin"), json={"motivo": "error"},
    )
    r = await client.post(
        f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/cobrar",
        headers=cab, json={"metodo": "efectivo"},
    )
    assert r.status_code == 409


# ── Aislamiento ──────────────────────────────────────────────────────────

async def test_no_se_ve_el_ticket_de_otro_tenant(dos_tenants, client):
    a, b = dos_tenants
    ticket_de_b = (await _ingresar(client, b, await _cab(client, b))).json()

    r = await client.get(
        f"/api/v1/t/{a.slug}/tickets/{ticket_de_b['id']}", headers=await _cab(client, a)
    )
    assert r.status_code == 404


async def test_no_se_cobra_el_ticket_de_otro_tenant(dos_tenants, client):
    a, b = dos_tenants
    ticket_de_b = (await _ingresar(client, b, await _cab(client, b))).json()

    r = await client.post(
        f"/api/v1/t/{a.slug}/tickets/{ticket_de_b['id']}/cobrar",
        headers=await _cab(client, a), json={"metodo": "efectivo"},
    )
    assert r.status_code == 404

    async with tenant_scope(b.id) as session:
        sigue = await session.get(Ticket, ticket_de_b["id"])
    assert sigue.estado.value == "abierto"


async def test_el_cobro_queda_en_la_bitacora(dos_tenants, client):
    from app.models.audit import AuditLog

    a, _ = dos_tenants
    cab = await _cab(client, a)
    ticket = (await _ingresar(client, a, cab)).json()
    await client.post(
        f"/api/v1/t/{a.slug}/tickets/{ticket['id']}/cobrar",
        headers=cab, json={"metodo": "efectivo"},
    )

    async with tenant_scope(a.id) as session:
        acciones = set((await session.scalars(select(AuditLog.accion))).all())
    assert {"ticket.open", "ticket.checkout"} <= acciones
