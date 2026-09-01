"""API de parametrización y tarifas."""

from decimal import Decimal

from sqlalchemy import select

from app.db.session import tenant_scope
from app.models.tarifa import EstadoPlan, RatePlan

from .conftest import cabecera, entrar


async def _admin(client, t):
    return cabecera(await entrar(client, t.slug, t.admin))


async def _operario(client, t):
    return cabecera(await entrar(client, t.slug, t.operario))


# ── Catálogos ────────────────────────────────────────────────────────────

async def test_los_tipos_de_vehiculo_vienen_del_tenant(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.get(f"/api/v1/t/{a.slug}/tipos-vehiculo", headers=await _admin(client, a))
    assert r.status_code == 200
    assert {t["codigo"] for t in r.json()} == {"carro", "moto", "bicicleta"}


async def test_hay_tipos_que_no_llevan_placa(dos_tenants, client):
    """Una bicicleta o un casco no tienen placa que anotar."""
    a, _ = dos_tenants
    r = await client.get(f"/api/v1/t/{a.slug}/tipos-vehiculo", headers=await _admin(client, a))
    porplaca = {t["codigo"]: t["requiere_placa"] for t in r.json()}
    assert porplaca["carro"] is True
    assert porplaca["bicicleta"] is False


async def test_el_admin_agrega_un_tipo_de_vehiculo_nuevo(dos_tenants, client):
    """Parametrizable de verdad: sin desplegar nada."""
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/tipos-vehiculo",
        headers=await _admin(client, a),
        json={"codigo": "patineta", "nombre": "Patineta eléctrica",
              "requiere_placa": False, "orden": 4},
    )
    assert r.status_code == 201
    assert r.json()["codigo"] == "patineta"


async def test_no_se_repite_el_codigo_de_tipo(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/tipos-vehiculo",
        headers=await _admin(client, a),
        json={"codigo": "carro", "nombre": "Otro carro"},
    )
    assert r.status_code == 409


async def test_al_operario_le_falta_permiso_para_tocar_el_catalogo(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/tipos-vehiculo",
        headers=await _operario(client, a),
        json={"codigo": "camion", "nombre": "Camión"},
    )
    assert r.status_code == 403
    assert "vehicle_type:manage" in r.json()["detail"]


async def test_desactivar_un_tipo_lo_saca_del_listado(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _admin(client, a)
    tipos = (await client.get(f"/api/v1/t/{a.slug}/tipos-vehiculo", headers=cab)).json()
    bici = next(t for t in tipos if t["codigo"] == "bicicleta")

    r = await client.patch(
        f"/api/v1/t/{a.slug}/tipos-vehiculo/{bici['id']}", headers=cab, json={"activo": False}
    )
    assert r.status_code == 200

    visibles = (await client.get(f"/api/v1/t/{a.slug}/tipos-vehiculo", headers=cab)).json()
    assert "bicicleta" not in {t["codigo"] for t in visibles}

    con_inactivos = (
        await client.get(f"/api/v1/t/{a.slug}/tipos-vehiculo?solo_activos=false", headers=cab)
    ).json()
    assert "bicicleta" in {t["codigo"] for t in con_inactivos}


async def test_los_articulos_tambien_son_del_tenant(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.get(f"/api/v1/t/{a.slug}/articulos", headers=await _admin(client, a))
    assert {x["codigo"] for x in r.json()} == {"casco", "lavada", "ticket_perdido"}


# ── Simulador ────────────────────────────────────────────────────────────

async def _plan_y_tipos(client, t):
    cab = await _admin(client, t)
    planes = (await client.get(f"/api/v1/t/{t.slug}/planes", headers=cab)).json()
    return cab, planes[0]["id"]


async def test_el_simulador_cotiza_hora_o_fraccion(dos_tenants, client):
    a, _ = dos_tenants
    cab, plan = await _plan_y_tipos(client, a)
    r = await client.post(
        f"/api/v1/t/{a.slug}/planes/{plan}/simular",
        headers=cab,
        json={"vehicle_type_id": str(a.tipos["carro"]),
              "entrada": "2026-08-24T13:00:00Z", "salida": "2026-08-24T15:17:00Z"},
    )
    assert r.status_code == 200
    d = r.json()
    assert Decimal(d["total"]) == Decimal("9000.00")
    assert d["minutos"] == 137
    assert d["regla_aplicada"] == "carro-general"


async def test_el_simulador_respeta_la_zona_horaria_de_la_sede(dos_tenants, client):
    """13:00 UTC son las 08:00 en Bogotá: tarifa diurna, no nocturna."""
    a, _ = dos_tenants
    cab, plan = await _plan_y_tipos(client, a)
    r = await client.post(
        f"/api/v1/t/{a.slug}/planes/{plan}/simular",
        headers=cab,
        json={"vehicle_type_id": str(a.tipos["carro"]),
              "entrada": "2026-08-25T00:00:00Z", "salida": "2026-08-25T03:00:00Z"},
    )
    # 19:00 → 22:00 en Bogotá: una hora diurna y dos nocturnas.
    assert Decimal(r.json()["total"]) == Decimal("7000.00")


async def test_el_simulador_suma_los_articulos(dos_tenants, client):
    a, _ = dos_tenants
    cab, plan = await _plan_y_tipos(client, a)
    r = await client.post(
        f"/api/v1/t/{a.slug}/planes/{plan}/simular",
        headers=cab,
        json={"vehicle_type_id": str(a.tipos["moto"]),
              "entrada": "2026-08-24T13:00:00Z", "salida": "2026-08-24T14:00:00Z",
              "items": [{"codigo": "casco", "cantidad": 2}]},
    )
    # dos fracciones de 30 min a 900 + dos cascos a 1000
    assert Decimal(r.json()["total"]) == Decimal("3800.00")


async def test_el_simulador_rechaza_una_salida_anterior(dos_tenants, client):
    a, _ = dos_tenants
    cab, plan = await _plan_y_tipos(client, a)
    r = await client.post(
        f"/api/v1/t/{a.slug}/planes/{plan}/simular",
        headers=cab,
        json={"vehicle_type_id": str(a.tipos["carro"]),
              "entrada": "2026-08-24T15:00:00Z", "salida": "2026-08-24T13:00:00Z"},
    )
    assert r.status_code == 400


async def test_el_simulador_avisa_de_un_articulo_inexistente(dos_tenants, client):
    a, _ = dos_tenants
    cab, plan = await _plan_y_tipos(client, a)
    r = await client.post(
        f"/api/v1/t/{a.slug}/planes/{plan}/simular",
        headers=cab,
        json={"vehicle_type_id": str(a.tipos["carro"]),
              "entrada": "2026-08-24T13:00:00Z", "salida": "2026-08-24T14:00:00Z",
              "items": [{"codigo": "helicoptero"}]},
    )
    assert r.status_code == 400
    assert "helicoptero" in r.json()["detail"]


# ── Ciclo de vida del plan ───────────────────────────────────────────────

async def test_publicar_una_version_nueva_archiva_la_anterior(dos_tenants, client):
    """El escenario del plan: sube la tarifa sin perder la versión vieja."""
    a, _ = dos_tenants
    cab = await _admin(client, a)

    creado = await client.post(
        f"/api/v1/t/{a.slug}/planes",
        headers=cab,
        json={
            "codigo": "general", "nombre": "Tarifa general 2027",
            "reglas": [{
                "codigo": "carro-general", "vehicle_type_id": str(a.tipos["carro"]),
                "modo": "por_bloque", "precio_bloque": "4000.00", "bloque_minutos": 60,
            }],
        },
    )
    assert creado.status_code == 201
    nuevo = creado.json()
    assert nuevo["version"] == 2
    assert nuevo["estado"] == "borrador"

    # En borrador ya se puede simular: es la red de seguridad antes de publicar.
    simulacion = await client.post(
        f"/api/v1/t/{a.slug}/planes/{nuevo['id']}/simular",
        headers=cab,
        json={"vehicle_type_id": str(a.tipos["carro"]),
              "entrada": "2026-08-24T13:00:00Z", "salida": "2026-08-24T14:00:00Z"},
    )
    assert Decimal(simulacion.json()["total"]) == Decimal("4000.00")

    activado = await client.post(f"/api/v1/t/{a.slug}/planes/{nuevo['id']}/activar", headers=cab)
    assert activado.status_code == 200
    assert activado.json()["estado"] == "activo"

    async with tenant_scope(a.id) as session:
        planes = {
            (p.codigo, p.version): p.estado
            for p in (await session.scalars(select(RatePlan))).all()
        }
    assert planes[("general", 1)] is EstadoPlan.ARCHIVADO
    assert planes[("general", 2)] is EstadoPlan.ACTIVO


async def test_un_plan_activo_no_se_edita(dos_tenants, client):
    """Se versiona, no se sobrescribe: los tickets abiertos dependen de él."""
    a, _ = dos_tenants
    cab, plan = await _plan_y_tipos(client, a)
    r = await client.post(
        f"/api/v1/t/{a.slug}/planes/{plan}/reglas",
        headers=cab,
        json={"codigo": "colada", "vehicle_type_id": str(a.tipos["carro"]),
              "modo": "por_bloque", "precio_bloque": "1.00"},
    )
    assert r.status_code == 409
    assert "versión nueva" in r.json()["detail"]


async def test_no_se_activa_un_plan_sin_tarifas(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _admin(client, a)
    vacio = (await client.post(
        f"/api/v1/t/{a.slug}/planes", headers=cab,
        json={"codigo": "vacio", "nombre": "Sin tarifas"},
    )).json()

    r = await client.post(f"/api/v1/t/{a.slug}/planes/{vacio['id']}/activar", headers=cab)
    assert r.status_code == 400


async def test_un_precio_en_cero_se_rechaza_al_crear(dos_tenants, client):
    """Cobrar gratis por descuido es peor que fallar en la validación."""
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/planes",
        headers=await _admin(client, a),
        json={"codigo": "gratis", "nombre": "Gratis",
              "reglas": [{"codigo": "x", "vehicle_type_id": str(a.tipos["carro"]),
                          "modo": "por_bloque"}]},
    )
    assert r.status_code == 422
    assert "precio_bloque" in str(r.json()["detail"])


async def test_los_escalones_no_pueden_dejar_huecos(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/planes",
        headers=await _admin(client, a),
        json={"codigo": "escalones", "nombre": "Con hueco",
              "reglas": [{
                  "codigo": "x", "vehicle_type_id": str(a.tipos["carro"]),
                  "modo": "escalonado",
                  "escalones": [
                      {"desde_minuto": 0, "hasta_minuto": 60, "precio": "3000", "unidad": "fijo"},
                      {"desde_minuto": 90, "precio": "2000"},
                  ],
              }]},
    )
    assert r.status_code == 422
    assert "hueco" in str(r.json()["detail"])


async def test_una_regla_de_un_tipo_ajeno_se_rechaza(dos_tenants, client):
    """El tipo de vehículo de otro tenant no existe desde aquí."""
    a, b = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/planes",
        headers=await _admin(client, a),
        json={"codigo": "cruzado", "nombre": "Cruzado",
              "reglas": [{"codigo": "x", "vehicle_type_id": str(b.tipos["carro"]),
                          "modo": "por_bloque", "precio_bloque": "3000"}]},
    )
    assert r.status_code == 400


async def test_no_se_ve_el_plan_de_otro_tenant_por_la_api(dos_tenants, client):
    a, b = dos_tenants
    _, plan_de_b = await _plan_y_tipos(client, b)
    r = await client.get(
        f"/api/v1/t/{a.slug}/planes/{plan_de_b}", headers=await _admin(client, a)
    )
    assert r.status_code == 404


async def test_activar_un_plan_queda_en_la_bitacora(dos_tenants, client):
    from app.models.audit import AuditLog

    a, _ = dos_tenants
    cab = await _admin(client, a)
    nuevo = (await client.post(
        f"/api/v1/t/{a.slug}/planes", headers=cab,
        json={"codigo": "auditado", "nombre": "Auditado",
              "reglas": [{"codigo": "r", "vehicle_type_id": str(a.tipos["carro"]),
                          "modo": "por_bloque", "precio_bloque": "3000"}]},
    )).json()
    await client.post(f"/api/v1/t/{a.slug}/planes/{nuevo['id']}/activar", headers=cab)

    async with tenant_scope(a.id) as session:
        acciones = set(
            (await session.scalars(select(AuditLog.accion))).all()
        )
    assert "plan_tarifario.create" in acciones
    assert "plan_tarifario.activate" in acciones


# ── Edición de un borrador ───────────────────────────────────────────────

async def _duplicar(client, t, cab):
    """Copia el plan vigente a un borrador, como hace la pantalla."""
    planes = (await client.get(f"/api/v1/t/{t.slug}/planes", headers=cab)).json()
    activo = next(p for p in planes if p["estado"] == "activo")
    detalle = (await client.get(
        f"/api/v1/t/{t.slug}/planes/{activo['id']}", headers=cab
    )).json()

    reglas = [
        {
            "codigo": r["codigo"],
            "vehicle_type_id": r["vehicle_type_id"],
            "modo": r["modo"],
            "precio_minuto": r["precio_minuto"],
            "precio_bloque": r["precio_bloque"],
            "precio_plena": r["precio_plena"],
            "precio_dia": r["precio_dia"],
            "bloque_minutos": r["bloque_minutos"],
            "dia_horas": r["dia_horas"],
            "gracia_minutos": r["gracia_minutos"],
            "cobro_minimo": r["cobro_minimo"],
            "tope_diario": r["tope_diario"],
            "tarifa_ticket_perdido": r["tarifa_ticket_perdido"],
            "redondeo_modo": r["redondeo_modo"],
            "redondeo_paso": r["redondeo_paso"],
            "impuesto_modo": r["impuesto_modo"],
            "impuesto_tasa": r["impuesto_tasa"],
            "prioridad": r["prioridad"],
            "escalones": r["escalones"],
            "franja": None if not r["tiene_franja"] else {
                "dias": r["franja_dias"],
                "desde_hora": r["franja_desde"],
                "hasta_hora": r["franja_hasta"],
                "incluye_festivos": r["franja_incluye_festivos"],
                "solo_festivos": r["franja_solo_festivos"],
            },
        }
        for r in detalle["reglas"]
    ]
    creado = await client.post(
        f"/api/v1/t/{t.slug}/planes", headers=cab,
        json={"codigo": detalle["codigo"], "nombre": "Copia", "reglas": reglas},
    )
    return detalle, creado


async def test_la_salida_trae_todo_lo_necesario_para_duplicar(dos_tenants, client):
    """Sin franja_incluye_festivos ni la tarifa de ticket perdido, copiar un
    plan desde la interfaz los borraría en silencio."""
    a, _ = dos_tenants
    cab = await _admin(client, a)
    planes = (await client.get(f"/api/v1/t/{a.slug}/planes", headers=cab)).json()
    detalle = (await client.get(
        f"/api/v1/t/{a.slug}/planes/{planes[0]['id']}", headers=cab
    )).json()

    campos = detalle["reglas"][0].keys()
    assert "franja_incluye_festivos" in campos
    assert "tarifa_ticket_perdido" in campos


async def test_duplicar_un_plan_conserva_franjas_y_escalones(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _admin(client, a)
    original, creado = await _duplicar(client, a, cab)
    assert creado.status_code == 201
    copia = creado.json()

    def resumen(plan):
        return sorted(
            (
                r["codigo"], r["modo"], str(r["precio_bloque"]), r["bloque_minutos"],
                r["tiene_franja"], str(r["franja_desde"]), str(r["franja_hasta"]),
                r["franja_incluye_festivos"], r["prioridad"],
            )
            for r in plan["reglas"]
        )

    assert resumen(copia) == resumen(original)
    assert copia["version"] == original["version"] + 1
    assert copia["estado"] == "borrador"


async def test_reemplazar_las_reglas_de_un_borrador(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _admin(client, a)
    _, creado = await _duplicar(client, a, cab)
    borrador = creado.json()

    r = await client.put(
        f"/api/v1/t/{a.slug}/planes/{borrador['id']}/reglas",
        headers=cab,
        json=[{
            "codigo": "carro-unico", "vehicle_type_id": str(a.tipos["carro"]),
            "modo": "por_bloque", "precio_bloque": "5000", "bloque_minutos": 60,
        }],
    )
    assert r.status_code == 200
    # Es un reemplazo: las reglas anteriores desaparecen.
    assert [x["codigo"] for x in r.json()["reglas"]] == ["carro-unico"]

    simulacion = await client.post(
        f"/api/v1/t/{a.slug}/planes/{borrador['id']}/simular",
        headers=cab,
        json={"vehicle_type_id": str(a.tipos["carro"]),
              "entrada": "2026-08-24T13:00:00Z", "salida": "2026-08-24T14:00:00Z"},
    )
    assert Decimal(simulacion.json()["total"]) == Decimal("5000.00")


async def test_no_se_reemplazan_las_reglas_de_un_plan_activo(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _admin(client, a)
    planes = (await client.get(f"/api/v1/t/{a.slug}/planes", headers=cab)).json()
    activo = next(p for p in planes if p["estado"] == "activo")

    r = await client.put(
        f"/api/v1/t/{a.slug}/planes/{activo['id']}/reglas",
        headers=cab,
        json=[{"codigo": "x", "vehicle_type_id": str(a.tipos["carro"]),
               "modo": "por_bloque", "precio_bloque": "1"}],
    )
    assert r.status_code == 409


async def test_descartar_un_borrador(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _admin(client, a)
    _, creado = await _duplicar(client, a, cab)
    borrador = creado.json()

    r = await client.delete(f"/api/v1/t/{a.slug}/planes/{borrador['id']}", headers=cab)
    assert r.status_code == 204

    ausente = await client.get(f"/api/v1/t/{a.slug}/planes/{borrador['id']}", headers=cab)
    assert ausente.status_code == 404


async def test_un_plan_publicado_no_se_borra(dos_tenants, client):
    """Es la historia con la que se cotizaron los tickets."""
    a, _ = dos_tenants
    cab = await _admin(client, a)
    planes = (await client.get(f"/api/v1/t/{a.slug}/planes", headers=cab)).json()
    activo = next(p for p in planes if p["estado"] == "activo")

    r = await client.delete(f"/api/v1/t/{a.slug}/planes/{activo['id']}", headers=cab)
    assert r.status_code == 409


async def test_al_operario_le_falta_permiso_para_editar_tarifas(dos_tenants, client):
    a, _ = dos_tenants
    planes = (await client.get(
        f"/api/v1/t/{a.slug}/planes", headers=await _admin(client, a)
    )).json()
    r = await client.delete(
        f"/api/v1/t/{a.slug}/planes/{planes[0]['id']}", headers=await _operario(client, a)
    )
    assert r.status_code == 403


# ── Salida para un parqueadero que se quedó sin tipos ─────────────────────

async def test_cargar_los_tipos_predeterminados(dos_tenants, client):
    """Salida por la interfaz para quien los borró todos o para los
    parqueaderos creados antes de que el alta los sembrara."""
    from sqlalchemy import delete

    from app.models.catalogo import VehicleType

    a, _ = dos_tenants
    cab = await _admin(client, a)

    async with tenant_scope(a.id) as session:
        await session.execute(delete(VehicleType))

    vacio = (await client.get(f"/api/v1/t/{a.slug}/tipos-vehiculo", headers=cab)).json()
    assert vacio == []

    r = await client.post(f"/api/v1/t/{a.slug}/tipos-vehiculo/predeterminados", headers=cab)
    assert r.status_code == 200
    assert {t["codigo"] for t in r.json()} == {"carro", "moto", "bicicleta"}


async def test_cargar_los_predeterminados_no_duplica(dos_tenants, client):
    a, _ = dos_tenants
    cab = await _admin(client, a)
    antes = (await client.get(f"/api/v1/t/{a.slug}/tipos-vehiculo", headers=cab)).json()

    await client.post(f"/api/v1/t/{a.slug}/tipos-vehiculo/predeterminados", headers=cab)
    despues = (await client.get(f"/api/v1/t/{a.slug}/tipos-vehiculo", headers=cab)).json()

    assert len(despues) == len(antes)


async def test_al_operario_le_falta_permiso_para_cargar_predeterminados(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/tipos-vehiculo/predeterminados",
        headers=await _operario(client, a),
    )
    assert r.status_code == 403


# ── Encender y apagar opciones ───────────────────────────────────────────
# El parqueadero define varias formas de cobrar el mismo vehículo y no
# siempre las ofrece todas. Apagar una no puede costarle el precio.

def _regla(tipo_id, codigo, **extra):
    base = {
        "codigo": codigo, "vehicle_type_id": str(tipo_id),
        "modo": "por_bloque", "precio_bloque": "3000", "bloque_minutos": 60,
    }
    return base | extra


async def test_una_opcion_apagada_conserva_su_precio(dos_tenants, client):
    """Apagarla y volver a encenderla no debe obligar a teclearla de nuevo."""
    a, _ = dos_tenants
    cab = await _admin(client, a)
    _, creado = await _duplicar(client, a, cab)
    borrador = creado.json()

    await client.put(
        f"/api/v1/t/{a.slug}/planes/{borrador['id']}/reglas", headers=cab,
        json=[
            _regla(a.tipos["carro"], "carro-hora", precio_bloque="3500"),
            _regla(a.tipos["carro"], "carro-plena", modo="plena",
                   precio_plena="12000", precio_bloque="0", activa=False),
        ],
    )

    detalle = (await client.get(
        f"/api/v1/t/{a.slug}/planes/{borrador['id']}", headers=cab
    )).json()
    apagada = next(r for r in detalle["reglas"] if r["codigo"] == "carro-plena")
    assert apagada["activa"] is False
    assert Decimal(apagada["precio_plena"]) == Decimal("12000.00")


async def test_una_opcion_apagada_puede_quedarse_sin_precio(dos_tenants, client):
    """Se guarda para llenarla después; mientras tanto no se cobra con ella."""
    a, _ = dos_tenants
    cab = await _admin(client, a)
    _, creado = await _duplicar(client, a, cab)
    borrador = creado.json()

    r = await client.put(
        f"/api/v1/t/{a.slug}/planes/{borrador['id']}/reglas", headers=cab,
        json=[
            _regla(a.tipos["carro"], "carro-hora"),
            _regla(a.tipos["carro"], "carro-minuto", modo="por_minuto",
                   precio_bloque="0", precio_minuto="0", activa=False),
        ],
    )
    assert r.status_code == 200


async def test_una_opcion_encendida_sin_precio_se_rechaza(dos_tenants, client):
    """Encendida y en cero cobraría gratis."""
    a, _ = dos_tenants
    cab = await _admin(client, a)
    _, creado = await _duplicar(client, a, cab)
    borrador = creado.json()

    r = await client.put(
        f"/api/v1/t/{a.slug}/planes/{borrador['id']}/reglas", headers=cab,
        json=[_regla(a.tipos["carro"], "carro-minuto", modo="por_minuto",
                     precio_bloque="0", precio_minuto="0", activa=True)],
    )
    assert r.status_code == 422


async def test_varias_tarifas_conviven_para_el_mismo_vehiculo(dos_tenants, client):
    """Es lo que pidió el usuario final: por hora, por fracción y por minuto
    rellenables a la vez."""
    a, _ = dos_tenants
    cab = await _admin(client, a)
    _, creado = await _duplicar(client, a, cab)
    borrador = creado.json()

    r = await client.put(
        f"/api/v1/t/{a.slug}/planes/{borrador['id']}/reglas", headers=cab,
        json=[
            _regla(a.tipos["carro"], "carro-hora", precio_bloque="3500",
                   bloque_minutos=60, prioridad=1),
            _regla(a.tipos["carro"], "carro-fraccion", precio_bloque="1000",
                   bloque_minutos=15),
            _regla(a.tipos["carro"], "carro-minuto", modo="por_minuto",
                   precio_bloque="0", precio_minuto="60"),
            _regla(a.tipos["carro"], "carro-plena", modo="plena",
                   precio_bloque="0", precio_plena="15000"),
        ],
    )
    assert r.status_code == 200
    assert len(r.json()["reglas"]) == 4

    # La marcada con prioridad es la que aplica el simulador.
    simulacion = await client.post(
        f"/api/v1/t/{a.slug}/planes/{borrador['id']}/simular", headers=cab,
        json={"vehicle_type_id": str(a.tipos["carro"]),
              "entrada": "2026-08-24T13:00:00Z", "salida": "2026-08-24T15:17:00Z"},
    )
    # Tres horas a 3.500
    assert Decimal(simulacion.json()["total"]) == Decimal("10500.00")
