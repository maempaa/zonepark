"""Alta de tenants y de sus miembros.

Estas funciones no abren sesión: reciben la que corresponda. Crear un
tenant desde cero necesita `system_scope` (todavía no hay tenant que
fijar); dar de alta a un miembro de un tenant existente va con
`tenant_scope`.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import PERMISOS, ROLES_SISTEMA
from app.core.security import hash_secreto
from app.models.parking_lot import DevicePolicy, ParkingLot
from app.models.rbac import MembershipRole, Permission, Role, RolePermission
from app.models.tenant import Tenant
from app.models.user import Membership, User

# Tipos de vehículo con los que arranca cualquier parqueadero. Son solo un
# punto de partida: el cliente los renombra, los desactiva o añade los
# suyos desde la pantalla de catálogo.
#
# Aquí no se siembran artículos ni tarifas **a propósito**: llevan precio,
# y un precio inventado que alguien cobre sin darse cuenta es peor que una
# pantalla vacía. Lo estructural se puede suponer; el dinero no.
TIPOS_POR_DEFECTO: list[tuple[str, str, str, bool, int]] = [
    # (código, nombre, icono, requiere placa, orden)
    ("carro", "Carro", "car", True, 1),
    ("moto", "Moto", "motorcycle", True, 2),
    ("bicicleta", "Bicicleta", "bike", False, 3),
]


async def sembrar_tipos_de_vehiculo(session: AsyncSession, tenant_id: uuid.UUID) -> int:
    """Crea los tipos que falten. Idempotente."""
    from app.models.catalogo import VehicleType

    creados = 0
    for codigo, nombre, icono, placa, orden in TIPOS_POR_DEFECTO:
        existe = await session.scalar(
            select(VehicleType).where(
                VehicleType.tenant_id == tenant_id, VehicleType.codigo == codigo
            )
        )
        if existe is None:
            session.add(
                VehicleType(
                    tenant_id=tenant_id, codigo=codigo, nombre=nombre, icono=icono,
                    requiere_placa=placa, orden=orden,
                )
            )
            creados += 1
    await session.flush()
    return creados


async def sembrar_permisos(session: AsyncSession) -> int:
    """Sincroniza el catálogo global de permisos. Idempotente."""
    filas = [
        {"codigo": p.codigo, "grupo": p.grupo, "descripcion": p.descripcion} for p in PERMISOS
    ]
    stmt = pg_insert(Permission).values(filas)
    await session.execute(
        stmt.on_conflict_do_update(
            index_elements=[Permission.codigo],
            set_={"grupo": stmt.excluded.grupo, "descripcion": stmt.excluded.descripcion},
        )
    )
    return len(filas)


async def provisionar_roles(session: AsyncSession, tenant_id: uuid.UUID) -> dict[str, Role]:
    """Crea los cuatro roles de sistema del tenant con sus permisos.

    Idempotente: si el rol ya existe, se le resincronizan los permisos.
    """
    roles: dict[str, Role] = {}
    for definicion in ROLES_SISTEMA:
        rol = await session.scalar(
            select(Role).where(Role.tenant_id == tenant_id, Role.codigo == definicion.codigo)
        )
        if rol is None:
            rol = Role(
                tenant_id=tenant_id,
                codigo=definicion.codigo,
                nombre=definicion.nombre,
                descripcion=definicion.descripcion,
                is_system=True,
            )
            session.add(rol)
            await session.flush()

        for codigo in definicion.permisos:
            await session.execute(
                pg_insert(RolePermission)
                .values(tenant_id=tenant_id, role_id=rol.id, permission_codigo=codigo)
                .on_conflict_do_nothing(index_elements=["role_id", "permission_codigo"])
            )
        roles[definicion.codigo] = rol

    return roles


async def crear_tenant(
    session: AsyncSession,
    *,
    slug: str,
    nombre: str,
    razon_social: str | None = None,
    nit: str | None = None,
) -> Tenant:
    tenant = Tenant(
        slug=slug.lower(),
        nombre=nombre,
        razon_social=razon_social,
        nit=nit,
    )
    session.add(tenant)
    await session.flush()
    await provisionar_roles(session, tenant.id)
    return tenant


async def crear_sede(
    session: AsyncSession,
    *,
    tenant: Tenant,
    codigo: str,
    nombre: str,
    direccion: str | None = None,
    device_policy: DevicePolicy = DevicePolicy.PIN_PERSISTENTE,
) -> ParkingLot:
    sede = ParkingLot(
        tenant_id=tenant.id,
        codigo=codigo,
        nombre=nombre,
        direccion=direccion,
        device_policy=device_policy,
        ticket_prefix=codigo[:8].upper(),
    )
    session.add(sede)
    await session.flush()
    return sede


async def crear_miembro(
    session: AsyncSession,
    *,
    tenant: Tenant,
    email: str,
    nombre: str,
    password: str,
    rol_codigo: str,
    pin: str | None = None,
    sedes: list[ParkingLot] | None = None,
    telefono: str | None = None,
) -> tuple[User, Membership]:
    """Da de alta a una persona en el tenant con un rol.

    Si el correo ya existe en la plataforma se reutiliza la cuenta: la
    misma persona puede trabajar en varios parqueaderos.

    `sedes` en None deja el rol con alcance a todo el tenant.
    """
    email = email.lower()
    user = await session.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(
            email=email,
            nombre=nombre,
            telefono=telefono,
            password_hash=hash_secreto(password),
        )
        session.add(user)
        await session.flush()

    membership = await session.scalar(
        select(Membership).where(
            Membership.tenant_id == tenant.id, Membership.user_id == user.id
        )
    )
    if membership is None:
        membership = Membership(tenant_id=tenant.id, user_id=user.id)
        session.add(membership)
        await session.flush()

    if pin:
        membership.pin_hash = hash_secreto(pin)

    rol = await session.scalar(
        select(Role).where(Role.tenant_id == tenant.id, Role.codigo == rol_codigo)
    )
    if rol is None:
        raise ValueError(f"El rol '{rol_codigo}' no existe en el tenant {tenant.slug}")

    destinos = [s.id for s in sedes] if sedes else [None]
    for lot_id in destinos:
        ya = await session.scalar(
            select(MembershipRole).where(
                MembershipRole.membership_id == membership.id,
                MembershipRole.role_id == rol.id,
                MembershipRole.parking_lot_id.is_(None)
                if lot_id is None
                else MembershipRole.parking_lot_id == lot_id,
            )
        )
        if ya is None:
            session.add(
                MembershipRole(
                    tenant_id=tenant.id,
                    membership_id=membership.id,
                    role_id=rol.id,
                    parking_lot_id=lot_id,
                )
            )

    await session.flush()
    return user, membership
