"""Inicio y cierre de sesión dentro de un tenant."""

from fastapi import APIRouter, Body, Request, status
from sqlalchemy import select

from app.deps import IdentidadDep, SesionDep, TenantDep
from app.models.user import Membership, User
from app.schemas.auth import LoginIn, MeOut, PinLoginIn, TokenOut
from app.services import audit
from app.services.auth import (
    emitir_tokens,
    login_con_password,
    login_con_pin,
    permisos_de_membresia,
    revocar_sesion,
    rotar_refresh,
)

router = APIRouter(prefix="/auth", tags=["autenticación"])


@router.post("/login", response_model=TokenOut)
async def login(
    datos: LoginIn,
    tenant: TenantDep,
    session: SesionDep,
    request: Request,
) -> TokenOut:
    user, membership, device_id = await login_con_password(
        session,
        tenant=tenant,
        email=datos.email,
        password=datos.password,
        device_fingerprint=datos.device_fingerprint,
        device_nombre=datos.device_nombre,
        user_agent=request.headers.get("user-agent"),
    )
    access, expira, refresh, refresh_expira = await emitir_tokens(
        session, tenant=tenant, user=user, membership=membership, device_id=device_id
    )
    await audit.registrar(
        session,
        accion="auth.login",
        entidad="user",
        entidad_id=user.id,
        tenant_id=tenant.id,
        actor_user_id=user.id,
        actor_email=user.email,
        request=request,
    )
    return TokenOut(
        access_token=access,
        expires_at=expira,
        refresh_token=refresh,
        refresh_expires_at=refresh_expira,
    )


@router.post("/pin-login", response_model=TokenOut)
async def pin_login(
    datos: PinLoginIn,
    tenant: TenantDep,
    session: SesionDep,
    request: Request,
) -> TokenOut:
    """Ingreso rápido del operario sobre un dispositivo ya registrado (D3)."""
    user, membership, device_id = await login_con_pin(
        session,
        tenant=tenant,
        email=datos.email,
        pin=datos.pin,
        device_fingerprint=datos.device_fingerprint,
    )
    access, expira, refresh, refresh_expira = await emitir_tokens(
        session, tenant=tenant, user=user, membership=membership, device_id=device_id
    )
    await audit.registrar(
        session,
        accion="auth.pin_login",
        entidad="user",
        entidad_id=user.id,
        tenant_id=tenant.id,
        actor_user_id=user.id,
        actor_email=user.email,
        request=request,
    )
    return TokenOut(
        access_token=access,
        expires_at=expira,
        refresh_token=refresh,
        refresh_expires_at=refresh_expira,
    )


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    tenant: TenantDep,
    session: SesionDep,
    refresh_token: str = Body(embed=True),
) -> TokenOut:
    user, membership, device_id, viejo = await rotar_refresh(
        session, tenant=tenant, refresh_crudo=refresh_token
    )
    access, expira, nuevo, refresh_expira = await emitir_tokens(
        session,
        tenant=tenant,
        user=user,
        membership=membership,
        device_id=device_id,
        reemplaza=viejo,
    )
    return TokenOut(
        access_token=access,
        expires_at=expira,
        refresh_token=nuevo,
        refresh_expires_at=refresh_expira,
    )


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(
    tenant: TenantDep,  # noqa: ARG001  (fija el contexto de RLS)
    session: SesionDep,
    refresh_token: str = Body(embed=True),
) -> None:
    await revocar_sesion(session, refresh_crudo=refresh_token)


@router.get("/me", response_model=MeOut)
async def me(tenant: TenantDep, session: SesionDep, identidad: IdentidadDep) -> MeOut:
    fila = (
        await session.execute(
            select(User, Membership)
            .join(Membership, Membership.user_id == User.id)
            .where(User.id == identidad.user_id)
        )
    ).first()
    user, membership = fila  # RLS garantiza que sea de este tenant

    permisos, sedes, roles = await permisos_de_membresia(session, membership.id)
    return MeOut(
        user_id=user.id,
        email=user.email,
        nombre=user.nombre,
        tenant_slug=tenant.slug,
        tenant_nombre=tenant.nombre,
        membership_id=membership.id,
        roles=roles,
        permisos=permisos,
        sedes=sedes,
        tiene_pin=membership.pin_hash is not None,
    )
