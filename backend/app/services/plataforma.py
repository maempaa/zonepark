"""Administración de la plataforma: alta de clientes.

Todo corre con `system_scope`, por encima de RLS. Es el único lugar del
sistema donde eso está justificado —crear un tenant es, por definición,
una acción anterior a que exista el tenant— y por eso cada operación
queda en la bitácora con `tenant_id` nulo.
"""

import uuid
from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.parking_lot import ParkingLot
from app.models.tenant import Tenant, TenantStatus
from app.models.ticket import EstadoTicket, Ticket
from app.models.user import Membership, User
from app.services.tenants import crear_miembro, crear_sede, crear_tenant, sembrar_permisos


class SlugOcupado(Exception):
    def __init__(self, slug: str) -> None:
        super().__init__(f"Ya existe un parqueadero con el identificador '{slug}'")


class CorreoOcupadoPorOtroAdmin(Exception):
    def __init__(self, email: str) -> None:
        super().__init__(f"'{email}' ya es administrador de la plataforma")


@dataclass(slots=True)
class ResumenTenant:
    id: uuid.UUID
    slug: str
    nombre: str
    status: str
    sedes: int
    usuarios: int
    adentro: int


async def listar_tenants(session: AsyncSession) -> list[ResumenTenant]:
    """Los clientes con sus cifras de un vistazo."""
    sedes = (
        select(ParkingLot.tenant_id, func.count().label("n"))
        .group_by(ParkingLot.tenant_id)
        .subquery()
    )
    usuarios = (
        select(Membership.tenant_id, func.count().label("n"))
        .group_by(Membership.tenant_id)
        .subquery()
    )
    adentro = (
        select(Ticket.tenant_id, func.count().label("n"))
        .where(Ticket.estado == EstadoTicket.ABIERTO)
        .group_by(Ticket.tenant_id)
        .subquery()
    )

    filas = (
        await session.execute(
            select(
                Tenant.id,
                Tenant.slug,
                Tenant.nombre,
                Tenant.status,
                func.coalesce(sedes.c.n, 0),
                func.coalesce(usuarios.c.n, 0),
                func.coalesce(adentro.c.n, 0),
            )
            .outerjoin(sedes, sedes.c.tenant_id == Tenant.id)
            .outerjoin(usuarios, usuarios.c.tenant_id == Tenant.id)
            .outerjoin(adentro, adentro.c.tenant_id == Tenant.id)
            .order_by(Tenant.nombre)
        )
    ).all()

    return [
        ResumenTenant(i, slug, nombre, str(status), s, u, a)
        for i, slug, nombre, status, s, u, a in filas
    ]


async def crear_cliente(
    session: AsyncSession,
    *,
    slug: str,
    nombre: str,
    razon_social: str | None,
    nit: str | None,
    admin_email: str,
    admin_nombre: str,
    admin_password: str,
    sede_codigo: str,
    sede_nombre: str,
) -> tuple[Tenant, User]:
    """Deja un parqueadero listo para operar en un solo paso.

    Un tenant sin roles, sin sede y sin nadie que pueda entrar no sirve de
    nada, así que las cuatro cosas nacen juntas. Si algo falla, la
    transacción las deshace todas: no queda un cliente a medio crear.
    """
    slug = slug.lower().strip()
    if await session.scalar(select(Tenant).where(Tenant.slug == slug)):
        raise SlugOcupado(slug)

    # El catálogo de permisos es global; asegurarlo aquí evita que un
    # despliegue nuevo cree tenants con roles vacíos.
    await sembrar_permisos(session)

    tenant = await crear_tenant(
        session, slug=slug, nombre=nombre, razon_social=razon_social, nit=nit
    )
    await crear_sede(session, tenant=tenant, codigo=sede_codigo, nombre=sede_nombre)
    user, _ = await crear_miembro(
        session,
        tenant=tenant,
        email=admin_email,
        nombre=admin_nombre,
        password=admin_password,
        rol_codigo="tenant_admin",
    )
    await session.flush()
    return tenant, user


async def cambiar_estado(
    session: AsyncSession, *, tenant: Tenant, status: TenantStatus
) -> Tenant:
    """Suspender corta el acceso de golpe: la resolución del tenant lo
    rechaza antes de mirar credenciales."""
    tenant.status = status
    await session.flush()
    return tenant


async def crear_admin_de_plataforma(
    session: AsyncSession, *, email: str, nombre: str, password: str
) -> User:
    from app.core.security import hash_secreto

    email = email.lower().strip()
    existente = await session.scalar(select(User).where(User.email == email))
    if existente is not None:
        if existente.is_platform_admin:
            raise CorreoOcupadoPorOtroAdmin(email)
        # La cuenta ya existe como usuario de algún parqueadero: se le
        # añade la marca en vez de duplicar la persona.
        existente.is_platform_admin = True
        await session.flush()
        return existente

    user = User(
        email=email,
        nombre=nombre,
        password_hash=hash_secreto(password),
        is_platform_admin=True,
    )
    session.add(user)
    await session.flush()
    return user
