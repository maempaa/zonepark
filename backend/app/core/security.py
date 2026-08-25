"""Contraseñas, PIN y tokens.

Contraseñas y PIN con argon2id. El PIN son 6 dígitos —espacio de búsqueda
diminuto—, así que su defensa real no es el hash sino el bloqueo por
intentos y que solo sirve sobre un dispositivo registrado (D3).

El token de acceso es un JWT corto que ya lleva los permisos, para no
consultar la base en cada petición. El precio es que revocar un rol tarda
hasta `access_token_minutes` en surtir efecto; a cambio, el refresh sí se
valida siempre contra la base y se puede cortar al instante.
"""

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.config import settings

_hasher = PasswordHasher()

ALGORITMO = "HS256"


# ── Contraseñas y PIN ────────────────────────────────────────────────────

def hash_secreto(valor: str) -> str:
    return _hasher.hash(valor)


def verificar_secreto(valor: str, hash_guardado: str) -> bool:
    try:
        return _hasher.verify(hash_guardado, valor)
    except (VerifyMismatchError, InvalidHashError):
        return False


def necesita_rehash(hash_guardado: str) -> bool:
    """True si el hash se creó con parámetros más débiles que los actuales."""
    try:
        return _hasher.check_needs_rehash(hash_guardado)
    except InvalidHashError:
        return False


# ── Token de acceso (JWT) ────────────────────────────────────────────────

def crear_token_de_acceso(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID | None,
    membership_id: uuid.UUID | None,
    permisos: list[str],
    sedes: list[uuid.UUID] | None,
    es_admin_plataforma: bool = False,
) -> tuple[str, datetime]:
    """Devuelve el token y su fecha de expiración.

    `sedes` en None significa "todas las del tenant".
    """
    ahora = datetime.now(UTC)
    expira = ahora + timedelta(minutes=settings.access_token_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tid": str(tenant_id) if tenant_id else None,
        "mem": str(membership_id) if membership_id else None,
        "perms": permisos,
        "lots": [str(s) for s in sedes] if sedes is not None else None,
        "plat": es_admin_plataforma,
        "typ": "access",
        "iat": int(ahora.timestamp()),
        "exp": int(expira.timestamp()),
        "jti": secrets.token_urlsafe(8),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm=ALGORITMO), expira


class TokenInvalido(Exception):
    pass


def leer_token_de_acceso(token: str) -> dict[str, Any]:
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[ALGORITMO])
    except jwt.ExpiredSignatureError as e:
        raise TokenInvalido("El token expiró") from e
    except jwt.InvalidTokenError as e:
        raise TokenInvalido("Token inválido") from e

    if payload.get("typ") != "access":
        raise TokenInvalido("Tipo de token incorrecto")
    return payload


# ── Refresh token ────────────────────────────────────────────────────────
# Opaco y aleatorio: en la base solo vive su hash, así que una copia de la
# tabla no permite suplantar a nadie.

def generar_refresh_token() -> tuple[str, str]:
    """Devuelve (token en claro, hash para guardar)."""
    crudo = secrets.token_urlsafe(48)
    return crudo, hash_refresh_token(crudo)


def hash_refresh_token(crudo: str) -> str:
    # SHA-256 y no argon2: se verifica buscando por el hash en un índice,
    # y el token ya tiene 288 bits de entropía, así que no hay nada que
    # proteger contra fuerza bruta.
    return hashlib.sha256(crudo.encode()).hexdigest()
