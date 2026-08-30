"""Panel de plataforma.

Estas rutas viven fuera del prefijo de tenant porque quien las usa no
pertenece a ninguno: crea clientes, no opera parqueaderos.

Todas corren con la sesión de sistema, por encima de RLS. Es el único
lugar del sistema donde eso está justificado, así que aquí la disciplina
es al revés que en el resto: cada acción se audita, y la pertenencia al
grupo se comprueba contra la base en cada petición, no contra el token.
"""

import uuid

from fastapi import APIRouter, Body, HTTPException, Request, status
from sqlalchemy import select

from app.deps import AdminPlataformaDep, SesionSistemaDep
from app.models.rbac import MembershipRole, Role
from app.models.tenant import Tenant, TenantStatus
from app.models.user import Membership, MembershipStatus, User
from app.schemas.auth import TokenOut
from app.schemas.plataforma import (
    AdminNuevoIn,
    AdminOut,
    ClienteNuevoIn,
    LoginPlataformaIn,
    MiembroNuevoIn,
    MiembroOut,
    TenantOut,
    TenantPatch,
    TenantResumenOut,
)
from app.services import audit
from app.services.auth import (
    emitir_tokens_plataforma,
    login_plataforma,
    revocar_sesion,
    rotar_refresh_plataforma,
)
from app.services.plataforma import (
    CorreoOcupadoPorOtroAdmin,
    SlugOcupado,
    cambiar_estado,
    crear_admin_de_plataforma,
    crear_cliente,
    listar_tenants,
)
from app.services.tenants import crear_miembro

router = APIRouter(prefix="/admin", tags=["plataforma"])


async def _tenant_o_404(session, tenant_id: uuid.UUID) -> Tenant:
    tenant = await session.get(Tenant, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe ese parqueadero")
    return tenant


# ── Sesión ───────────────────────────────────────────────────────────────

@router.post("/auth/login", response_model=TokenOut)
async def login(
    datos: LoginPlataformaIn, session: SesionSistemaDep, request: Request
) -> TokenOut:
    user = await login_plataforma(session, email=datos.email, password=datos.password)
    access, expira, refresh, refresh_expira = await emitir_tokens_plataforma(
        session, user=user
    )
    await audit.registrar(
        session, accion="plataforma.login", entidad="user", entidad_id=user.id,
        actor_user_id=user.id, actor_email=user.email, request=request,
    )
    return TokenOut(
        access_token=access, expires_at=expira,
        refresh_token=refresh, refresh_expires_at=refresh_expira,
    )


@router.post("/auth/refresh", response_model=TokenOut)
async def refrescar(
    session: SesionSistemaDep, refresh_token: str = Body(embed=True)
) -> TokenOut:
    user, viejo = await rotar_refresh_plataforma(session, refresh_crudo=refresh_token)
    access, expira, nuevo, refresh_expira = await emitir_tokens_plataforma(
        session, user=user, reemplaza=viejo
    )
    return TokenOut(
        access_token=access, expires_at=expira,
        refresh_token=nuevo, refresh_expires_at=refresh_expira,
    )


@router.post("/auth/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(session: SesionSistemaDep, refresh_token: str = Body(embed=True)) -> None:
    await revocar_sesion(session, refresh_crudo=refresh_token)


@router.get("/me", response_model=AdminOut)
async def yo(admin: AdminPlataformaDep, session: SesionSistemaDep) -> User:
    return await session.get(User, admin.user_id)


# ── Clientes ─────────────────────────────────────────────────────────────

@router.get("/tenants", response_model=list[TenantResumenOut])
async def listar(admin: AdminPlataformaDep, session: SesionSistemaDep) -> list[dict]:
    return [
        {
            "id": r.id, "slug": r.slug, "nombre": r.nombre, "status": r.status,
            "sedes": r.sedes, "usuarios": r.usuarios, "adentro": r.adentro,
        }
        for r in await listar_tenants(session)
    ]


@router.post("/tenants", response_model=TenantOut, status_code=status.HTTP_201_CREATED)
async def crear(
    datos: ClienteNuevoIn,
    admin: AdminPlataformaDep,
    session: SesionSistemaDep,
    request: Request,
) -> Tenant:
    """Deja el parqueadero listo para operar: tenant, roles, sede y un
    administrador que puede entrar. Todo en una transacción."""
    try:
        tenant, user = await crear_cliente(
            session,
            slug=datos.slug,
            nombre=datos.nombre,
            razon_social=datos.razon_social,
            nit=datos.nit,
            admin_email=datos.admin_email,
            admin_nombre=datos.admin_nombre,
            admin_password=datos.admin_password,
            sede_codigo=datos.sede_codigo,
            sede_nombre=datos.sede_nombre,
        )
    except SlugOcupado as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    await audit.registrar(
        session, accion="plataforma.tenant_create", entidad="tenant",
        entidad_id=tenant.id, actor_user_id=admin.user_id, actor_email=admin.email,
        despues={"slug": tenant.slug, "admin": user.email}, request=request,
    )
    return tenant


@router.get("/tenants/{tenant_id}", response_model=TenantOut)
async def ver(
    tenant_id: uuid.UUID, admin: AdminPlataformaDep, session: SesionSistemaDep
) -> Tenant:
    return await _tenant_o_404(session, tenant_id)


@router.patch("/tenants/{tenant_id}", response_model=TenantOut)
async def editar(
    tenant_id: uuid.UUID,
    datos: TenantPatch,
    admin: AdminPlataformaDep,
    session: SesionSistemaDep,
    request: Request,
) -> Tenant:
    """Suspender corta el acceso de golpe: la resolución del tenant lo
    rechaza antes de mirar credenciales."""
    tenant = await _tenant_o_404(session, tenant_id)
    cambios = datos.model_dump(exclude_unset=True)
    antes = {c: str(getattr(tenant, c)) for c in cambios}

    if "status" in cambios:
        await cambiar_estado(session, tenant=tenant, status=TenantStatus(cambios.pop("status")))
    for campo, valor in cambios.items():
        setattr(tenant, campo, valor)
    await session.flush()

    await audit.registrar(
        session, accion="plataforma.tenant_update", entidad="tenant",
        entidad_id=tenant.id, actor_user_id=admin.user_id, actor_email=admin.email,
        antes=antes, despues={k: str(v) for k, v in datos.model_dump(exclude_unset=True).items()},
        request=request,
    )
    return tenant


# ── Personas de un cliente ───────────────────────────────────────────────

@router.get("/tenants/{tenant_id}/usuarios", response_model=list[MiembroOut])
async def miembros(
    tenant_id: uuid.UUID, admin: AdminPlataformaDep, session: SesionSistemaDep
) -> list[dict]:
    await _tenant_o_404(session, tenant_id)
    filas = (
        await session.execute(
            select(User, Membership, Role.codigo)
            .join(Membership, Membership.user_id == User.id)
            .outerjoin(MembershipRole, MembershipRole.membership_id == Membership.id)
            .outerjoin(Role, Role.id == MembershipRole.role_id)
            .where(Membership.tenant_id == tenant_id)
            .order_by(User.nombre)
        )
    ).all()

    agrupados: dict[uuid.UUID, dict] = {}
    for user, membresia, rol in filas:
        fila = agrupados.setdefault(
            user.id,
            {
                "user_id": user.id,
                "membership_id": membresia.id,
                "email": user.email,
                "nombre": user.nombre,
                "roles": [],
                "activo": user.is_active and membresia.status is MembershipStatus.ACTIVA,
            },
        )
        if rol and rol not in fila["roles"]:
            fila["roles"].append(rol)
    return list(agrupados.values())


@router.post(
    "/tenants/{tenant_id}/usuarios", response_model=MiembroOut,
    status_code=status.HTTP_201_CREATED,
)
async def agregar_miembro(
    tenant_id: uuid.UUID,
    datos: MiembroNuevoIn,
    admin: AdminPlataformaDep,
    session: SesionSistemaDep,
    request: Request,
) -> dict:
    tenant = await _tenant_o_404(session, tenant_id)
    try:
        user, membresia = await crear_miembro(
            session, tenant=tenant, email=datos.email, nombre=datos.nombre,
            password=datos.password, rol_codigo=datos.rol,
        )
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    await audit.registrar(
        session, accion="plataforma.usuario_create", entidad="user", entidad_id=user.id,
        tenant_id=tenant.id, actor_user_id=admin.user_id, actor_email=admin.email,
        despues={"email": user.email, "rol": datos.rol}, request=request,
    )
    return {
        "user_id": user.id, "membership_id": membresia.id, "email": user.email,
        "nombre": user.nombre, "roles": [datos.rol], "activo": True,
    }


# ── Administradores de plataforma ────────────────────────────────────────

@router.get("/usuarios", response_model=list[AdminOut])
async def administradores(
    admin: AdminPlataformaDep, session: SesionSistemaDep
) -> list[User]:
    return list(
        (
            await session.scalars(
                select(User).where(User.is_platform_admin.is_(True)).order_by(User.nombre)
            )
        ).all()
    )


@router.post("/usuarios", response_model=AdminOut, status_code=status.HTTP_201_CREATED)
async def crear_administrador(
    datos: AdminNuevoIn,
    admin: AdminPlataformaDep,
    session: SesionSistemaDep,
    request: Request,
) -> User:
    try:
        user = await crear_admin_de_plataforma(
            session, email=datos.email, nombre=datos.nombre, password=datos.password
        )
    except CorreoOcupadoPorOtroAdmin as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    await audit.registrar(
        session, accion="plataforma.admin_create", entidad="user", entidad_id=user.id,
        actor_user_id=admin.user_id, actor_email=admin.email,
        despues={"email": user.email}, request=request,
    )
    return user


@router.delete("/usuarios/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def quitar_administrador(
    user_id: uuid.UUID,
    admin: AdminPlataformaDep,
    session: SesionSistemaDep,
    request: Request,
) -> None:
    """Quita la marca de plataforma. No borra la persona: puede seguir
    siendo usuario de algún parqueadero."""
    if user_id == admin.user_id:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "No puedes quitarte a ti mismo la administración"
        )

    user = await session.get(User, user_id)
    if user is None or not user.is_platform_admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No es administrador de plataforma")

    # No hace falta comprobar que quede alguien: solo se pueden quitar
    # otros, nunca uno mismo, así que quien ejecuta esto siempre queda.
    user.is_platform_admin = False
    await audit.registrar(
        session, accion="plataforma.admin_revoke", entidad="user", entidad_id=user.id,
        actor_user_id=admin.user_id, actor_email=admin.email,
        antes={"email": user.email}, request=request,
    )
