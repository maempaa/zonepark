"""Inicio de sesión, bloqueo por intentos y rotación de tokens."""

from sqlalchemy import select

from app.config import settings
from app.db.session import system_scope, tenant_scope
from app.models.device import Device
from app.models.parking_lot import DevicePolicy, ParkingLot

from .conftest import CLAVE, PIN, cabecera, entrar


async def test_login_correcto_devuelve_los_dos_tokens(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/login", json={"email": a.admin, "password": CLAVE}
    )
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["access_token"] and cuerpo["refresh_token"]
    assert cuerpo["token_type"] == "bearer"


async def test_password_incorrecta(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/login", json={"email": a.admin, "password": "equivocada"}
    )
    assert r.status_code == 401


async def test_correo_inexistente_da_el_mismo_error_que_una_clave_mala(dos_tenants, client):
    """No se puede distinguir un correo válido de uno inventado."""
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/login",
        json={"email": "nadie@prueba.com.co", "password": CLAVE},
    )
    assert r.status_code == 401
    assert r.json()["detail"] == "Correo o contraseña incorrectos"


async def test_la_cuenta_se_bloquea_tras_varios_intentos(dos_tenants, client):
    a, _ = dos_tenants
    ruta = f"/api/v1/t/{a.slug}/auth/login"

    for _ in range(settings.max_failed_attempts):
        r = await client.post(ruta, json={"email": a.admin, "password": "equivocada"})
        assert r.status_code == 401

    # El siguiente intento ya no es un 401: la cuenta está bloqueada.
    r = await client.post(ruta, json={"email": a.admin, "password": "equivocada"})
    assert r.status_code == 429

    # Y ni siquiera la contraseña correcta la desbloquea antes de tiempo.
    r = await client.post(ruta, json={"email": a.admin, "password": CLAVE})
    assert r.status_code == 429
    assert "bloqueada_hasta" in r.json()


async def test_me_requiere_token(dos_tenants, client):
    a, _ = dos_tenants
    assert (await client.get(f"/api/v1/t/{a.slug}/auth/me")).status_code == 401
    r = await client.get(f"/api/v1/t/{a.slug}/auth/me", headers=cabecera("basura"))
    assert r.status_code == 401


async def test_me_describe_al_usuario(dos_tenants, client):
    a, _ = dos_tenants
    token = await entrar(client, a.slug, a.admin)
    cuerpo = (await client.get(f"/api/v1/t/{a.slug}/auth/me", headers=cabecera(token))).json()

    assert cuerpo["email"] == a.admin
    assert cuerpo["tenant_slug"] == a.slug
    assert cuerpo["roles"] == ["tenant_admin"]
    assert cuerpo["sedes"] is None, "El administrador alcanza todas las sedes"
    assert "lot:manage" in cuerpo["permisos"]


async def test_el_operario_llega_con_alcance_limitado(dos_tenants, client):
    a, _ = dos_tenants
    token = await entrar(client, a.slug, a.operario)
    cuerpo = (await client.get(f"/api/v1/t/{a.slug}/auth/me", headers=cabecera(token))).json()

    assert cuerpo["roles"] == ["operator"]
    assert cuerpo["sedes"] == [str(a.sede_asignada)]
    assert "lot:manage" not in cuerpo["permisos"]
    assert cuerpo["tiene_pin"] is True


# ── Rotación del refresh ─────────────────────────────────────────────────

async def _login_completo(client, slug, email):
    r = await client.post(f"/api/v1/t/{slug}/auth/login", json={"email": email, "password": CLAVE})
    return r.json()


async def test_el_refresh_rota_y_el_anterior_deja_de_servir(dos_tenants, client):
    a, _ = dos_tenants
    ruta = f"/api/v1/t/{a.slug}/auth/refresh"
    primero = (await _login_completo(client, a.slug, a.admin))["refresh_token"]

    r = await client.post(ruta, json={"refresh_token": primero})
    assert r.status_code == 200
    segundo = r.json()["refresh_token"]
    assert segundo != primero

    assert (await client.post(ruta, json={"refresh_token": segundo})).status_code == 200


async def test_reutilizar_un_refresh_viejo_corta_toda_la_cadena(dos_tenants, client):
    """Si aparece un token ya rotado, se asume robo y se revoca todo."""
    a, _ = dos_tenants
    ruta = f"/api/v1/t/{a.slug}/auth/refresh"
    primero = (await _login_completo(client, a.slug, a.admin))["refresh_token"]
    segundo = (await client.post(ruta, json={"refresh_token": primero})).json()["refresh_token"]

    robado = await client.post(ruta, json={"refresh_token": primero})
    assert robado.status_code == 401

    # El token legítimo también cae: es el precio de cortar la sesión robada.
    assert (await client.post(ruta, json={"refresh_token": segundo})).status_code == 401


async def test_logout_revoca_la_sesion(dos_tenants, client):
    a, _ = dos_tenants
    tokens = await _login_completo(client, a.slug, a.admin)
    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/logout", json={"refresh_token": tokens["refresh_token"]}
    )
    assert r.status_code == 204

    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/refresh", json={"refresh_token": tokens["refresh_token"]}
    )
    assert r.status_code == 401


# ── PIN y dispositivos (D3) ──────────────────────────────────────────────

async def test_pin_funciona_en_el_dispositivo_registrado(dos_tenants, client):
    a, _ = dos_tenants
    huella = "caseta-de-prueba"

    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/login",
        json={
            "email": a.operario,
            "password": CLAVE,
            "device_fingerprint": huella,
            "device_nombre": "Tablet de la caseta",
        },
    )
    assert r.status_code == 200

    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/pin-login",
        json={"email": a.operario, "pin": PIN, "device_fingerprint": huella},
    )
    assert r.status_code == 200


async def test_el_pin_no_sirve_desde_un_dispositivo_desconocido(dos_tenants, client):
    a, _ = dos_tenants
    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/pin-login",
        json={"email": a.operario, "pin": PIN, "device_fingerprint": "celular-ajeno"},
    )
    assert r.status_code == 403


async def test_pin_incorrecto(dos_tenants, client):
    a, _ = dos_tenants
    huella = "caseta-pin-malo"
    await client.post(
        f"/api/v1/t/{a.slug}/auth/login",
        json={"email": a.operario, "password": CLAVE, "device_fingerprint": huella},
    )
    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/pin-login",
        json={"email": a.operario, "pin": "000000", "device_fingerprint": huella},
    )
    assert r.status_code == 401


async def test_una_sede_de_login_por_turno_no_acepta_pin(dos_tenants, client):
    """D3: la política de la sede manda sobre el dispositivo."""
    a, _ = dos_tenants
    huella = "tablet-sede-estricta"

    await client.post(
        f"/api/v1/t/{a.slug}/auth/login",
        json={"email": a.operario, "password": CLAVE, "device_fingerprint": huella},
    )

    # Se ata el dispositivo a la sede que exige contraseña en cada turno.
    async with tenant_scope(a.id) as session:
        device = await session.scalar(select(Device).where(Device.fingerprint == huella))
        sede = await session.get(ParkingLot, a.sede_ajena)
        assert sede.device_policy is DevicePolicy.LOGIN_POR_TURNO
        device.parking_lot_id = sede.id

    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/pin-login",
        json={"email": a.operario, "pin": PIN, "device_fingerprint": huella},
    )
    assert r.status_code == 403
    assert "cada turno" in r.json()["detail"]


async def test_el_dispositivo_revocado_deja_de_servir(dos_tenants, client):
    a, _ = dos_tenants
    huella = "tablet-revocada"
    await client.post(
        f"/api/v1/t/{a.slug}/auth/login",
        json={"email": a.operario, "password": CLAVE, "device_fingerprint": huella},
    )

    async with tenant_scope(a.id) as session:
        from datetime import UTC, datetime

        device = await session.scalar(select(Device).where(Device.fingerprint == huella))
        device.revoked_at = datetime.now(UTC)

    r = await client.post(
        f"/api/v1/t/{a.slug}/auth/pin-login",
        json={"email": a.operario, "pin": PIN, "device_fingerprint": huella},
    )
    assert r.status_code == 403


async def test_el_refresh_token_se_guarda_hasheado(dos_tenants, client):
    """Una copia de la tabla no debe permitir suplantar a nadie."""
    a, _ = dos_tenants
    tokens = await _login_completo(client, a.slug, a.admin)
    crudo = tokens["refresh_token"]

    async with system_scope() as session:
        from app.models.token import RefreshToken

        guardados = list((await session.scalars(select(RefreshToken.token_hash))).all())

    assert crudo not in guardados
