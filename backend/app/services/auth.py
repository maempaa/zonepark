"""Inicio de sesión, permisos efectivos y rotación de tokens.

Todo esto corre dentro de una sesión con RLS activo. Eso da una propiedad
que conviene entender: la política de `users` solo deja ver a quienes son
miembros del tenant, así que un correo válido de *otro* parqueadero
sencillamente no existe desde aquí. No hay que comprobarlo a mano.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.core.security import (
    crear_token_de_acceso,
    generar_refresh_token,
    hash_refresh_token,
    hash_secreto,
    necesita_rehash,
    verificar_secreto,
)
from app.models.device import Device
from app.models.parking_lot import DevicePolicy, ParkingLot
from app.models.rbac import MembershipRole, Role, RolePermission
from app.models.tenant import Tenant
from app.models.token import RefreshToken
from app.models.user import Membership, MembershipStatus, User


class CredencialesInvalidas(Exception):
    """Mensaje deliberadamente vago: no revela si el correo existe."""

    def __init__(self, detalle: str = "Correo o contraseña incorrectos") -> None:
        super().__init__(detalle)


class CuentaBloqueada(Exception):
    def __init__(self, hasta: datetime) -> None:
        self.hasta = hasta
        minutos = max(1, round((hasta - datetime.now(UTC)).total_seconds() / 60))
        super().__init__(f"Cuenta bloqueada por intentos fallidos. Reintenta en {minutos} min.")


class DispositivoNoAutorizado(Exception):
    def __init__(self, detalle: str = "Este dispositivo no está autorizado") -> None:
        super().__init__(detalle)


# ── Permisos efectivos ───────────────────────────────────────────────────

async def permisos_de_membresia(
    session: AsyncSession, membership_id: uuid.UUID
) -> tuple[list[str], list[uuid.UUID] | None, list[str]]:
    """Devuelve (permisos, sedes, códigos de rol).

    `sedes` en None significa "todas": basta con que una sola asignación de
    rol no tenga sede para que el alcance sea el tenant completo.
    """
    filas = (
        await session.execute(
            select(Role.codigo, RolePermission.permission_codigo, MembershipRole.parking_lot_id)
            .select_from(MembershipRole)
            .join(Role, Role.id == MembershipRole.role_id)
            .outerjoin(RolePermission, RolePermission.role_id == Role.id)
            .where(MembershipRole.membership_id == membership_id)
        )
    ).all()

    permisos = {p for _, p, _ in filas if p}
    roles = {r for r, _, _ in filas}
    sedes: set[uuid.UUID] = set()
    alcance_total = False
    for _, _, lot_id in filas:
        if lot_id is None:
            alcance_total = True
        else:
            sedes.add(lot_id)

    return sorted(permisos), (None if alcance_total else sorted(sedes)), sorted(roles)


# ── Bloqueo por intentos ─────────────────────────────────────────────────

async def _registrar_fallo(session: AsyncSession, user: User) -> None:
    """Suma un intento fallido y bloquea la cuenta al llegar al límite.

    El commit aquí es deliberado y necesario. Quien llama lanza
    `CredencialesInvalidas` justo después, y esa excepción hace rollback de
    la transacción de la petición: sin este commit el contador volvería a
    cero en cada intento y el bloqueo no se activaría nunca.
    """
    intentos = user.failed_attempts + 1
    valores: dict = {"failed_attempts": intentos}
    if intentos >= settings.max_failed_attempts:
        valores["locked_until"] = datetime.now(UTC) + timedelta(minutes=settings.lockout_minutes)
        valores["failed_attempts"] = 0
    await session.execute(update(User).where(User.id == user.id).values(**valores))
    await session.commit()


async def _registrar_exito(session: AsyncSession, user: User, password: str | None) -> None:
    valores: dict = {
        "failed_attempts": 0,
        "locked_until": None,
        "last_login_at": datetime.now(UTC),
    }
    # Si los parámetros de argon2 subieron desde la última vez, se re-hashea
    # aprovechando que aquí tenemos la contraseña en claro.
    if password is not None and necesita_rehash(user.password_hash):
        valores["password_hash"] = hash_secreto(password)
    await session.execute(update(User).where(User.id == user.id).values(**valores))


def _verificar_no_bloqueado(user: User) -> None:
    if user.locked_until and user.locked_until > datetime.now(UTC):
        raise CuentaBloqueada(user.locked_until)


# ── Emisión de tokens ────────────────────────────────────────────────────

async def emitir_tokens(
    session: AsyncSession,
    *,
    tenant: Tenant,
    user: User,
    membership: Membership,
    device_id: uuid.UUID | None = None,
    reemplaza: RefreshToken | None = None,
) -> tuple[str, datetime, str, datetime]:
    permisos, sedes, _ = await permisos_de_membresia(session, membership.id)

    access, expira = crear_token_de_acceso(
        user_id=user.id,
        tenant_id=tenant.id,
        membership_id=membership.id,
        permisos=permisos,
        sedes=sedes,
        es_admin_plataforma=user.is_platform_admin,
    )

    crudo, token_hash = generar_refresh_token()
    refresh_expira = datetime.now(UTC) + timedelta(days=settings.refresh_token_days)
    nuevo = RefreshToken(
        tenant_id=tenant.id,
        user_id=user.id,
        device_id=device_id,
        token_hash=token_hash,
        expires_at=refresh_expira,
    )
    session.add(nuevo)
    await session.flush()

    # Encadenar permite detectar la reutilización de un token viejo.
    if reemplaza is not None:
        reemplaza.replaced_by_id = nuevo.id

    return access, expira, crudo, refresh_expira


# ── Login con contraseña ─────────────────────────────────────────────────

async def _buscar_membresia_activa(
    session: AsyncSession, email: str
) -> tuple[User, Membership]:
    fila = (
        await session.execute(
            select(User, Membership)
            .join(Membership, Membership.user_id == User.id)
            .where(User.email == email.lower())
        )
    ).first()

    if fila is None:
        # Puede ser que el correo no exista o que no sea miembro de este
        # tenant (RLS lo oculta). Da igual: mismo mensaje.
        raise CredencialesInvalidas()

    user, membership = fila
    if not user.is_active or membership.status is not MembershipStatus.ACTIVA:
        raise CredencialesInvalidas("La cuenta está desactivada")
    return user, membership


async def login_con_password(
    session: AsyncSession,
    *,
    tenant: Tenant,
    email: str,
    password: str,
    device_fingerprint: str | None = None,
    device_nombre: str | None = None,
    user_agent: str | None = None,
) -> tuple[User, Membership, uuid.UUID | None]:
    user, membership = await _buscar_membresia_activa(session, email)
    _verificar_no_bloqueado(user)

    if not verificar_secreto(password, user.password_hash):
        await _registrar_fallo(session, user)
        raise CredencialesInvalidas()

    await _registrar_exito(session, user, password)

    device_id = None
    if device_fingerprint:
        device = await registrar_dispositivo(
            session,
            tenant=tenant,
            membership=membership,
            fingerprint=device_fingerprint,
            nombre=device_nombre or "Dispositivo",
            user_agent=user_agent,
        )
        device_id = device.id

    return user, membership, device_id


# ── Dispositivos y login con PIN (D3) ────────────────────────────────────

async def registrar_dispositivo(
    session: AsyncSession,
    *,
    tenant: Tenant,
    membership: Membership,
    fingerprint: str,
    nombre: str,
    user_agent: str | None = None,
) -> Device:
    device = await session.scalar(
        select(Device).where(
            Device.membership_id == membership.id,
            Device.fingerprint == fingerprint,
        )
    )
    if device is None:
        device = Device(
            tenant_id=tenant.id,
            membership_id=membership.id,
            fingerprint=fingerprint,
            nombre=nombre,
            user_agent=user_agent,
        )
        session.add(device)
    else:
        # Volver a entrar con contraseña reactiva un dispositivo revocado:
        # es la vía de recuperación cuando el operario pierde el acceso.
        device.revoked_at = None
        device.user_agent = user_agent or device.user_agent
    device.last_seen_at = datetime.now(UTC)
    await session.flush()
    return device


async def login_con_pin(
    session: AsyncSession,
    *,
    tenant: Tenant,
    email: str,
    pin: str,
    device_fingerprint: str,
) -> tuple[User, Membership, uuid.UUID]:
    user, membership = await _buscar_membresia_activa(session, email)
    _verificar_no_bloqueado(user)

    if not membership.pin_hash:
        raise DispositivoNoAutorizado("Esta cuenta no tiene PIN configurado")

    device = await session.scalar(
        select(Device).where(
            Device.membership_id == membership.id,
            Device.fingerprint == device_fingerprint,
        )
    )
    if device is None or device.revoked_at is not None:
        raise DispositivoNoAutorizado()

    # D3: en las sedes que exigen login por turno, el PIN no basta.
    if device.parking_lot_id is not None:
        sede = await session.get(ParkingLot, device.parking_lot_id)
        if sede is not None and sede.device_policy is DevicePolicy.LOGIN_POR_TURNO:
            raise DispositivoNoAutorizado(
                "Esta sede exige iniciar sesión con contraseña en cada turno"
            )

    if not verificar_secreto(pin, membership.pin_hash):
        await _registrar_fallo(session, user)
        raise CredencialesInvalidas("PIN incorrecto")

    await _registrar_exito(session, user, None)
    device.last_seen_at = datetime.now(UTC)
    return user, membership, device.id


# ── Rotación del refresh ─────────────────────────────────────────────────

async def rotar_refresh(
    session: AsyncSession, *, tenant: Tenant, refresh_crudo: str
) -> tuple[User, Membership, uuid.UUID | None, RefreshToken]:
    token_hash = hash_refresh_token(refresh_crudo)
    guardado = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == token_hash)
    )
    if guardado is None:
        raise CredencialesInvalidas("Sesión inválida")

    ahora = datetime.now(UTC)

    # Reutilización de un token ya rotado: señal de robo. Se corta toda la
    # cadena de sesiones de ese usuario, no solo esta.
    if guardado.revoked_at is not None or guardado.replaced_by_id is not None:
        await session.execute(
            update(RefreshToken)
            .where(RefreshToken.user_id == guardado.user_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=ahora)
        )
        # Igual que en `_registrar_fallo`: hay que confirmar antes de lanzar,
        # porque la excepción hace rollback de la transacción de la petición
        # y la revocación se perdería justo cuando más importa.
        await session.commit()
        raise CredencialesInvalidas("La sesión fue revocada por seguridad")

    if guardado.expires_at <= ahora:
        raise CredencialesInvalidas("La sesión expiró")

    user = await session.get(User, guardado.user_id)
    membership = await session.scalar(
        select(Membership).where(Membership.user_id == guardado.user_id)
    )
    if user is None or membership is None or not user.is_active:
        raise CredencialesInvalidas("Sesión inválida")

    guardado.revoked_at = ahora
    return user, membership, guardado.device_id, guardado


async def revocar_sesion(session: AsyncSession, *, refresh_crudo: str) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.token_hash == hash_refresh_token(refresh_crudo))
        .values(revoked_at=datetime.now(UTC))
    )
