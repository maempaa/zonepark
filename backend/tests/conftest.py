"""Infraestructura de las pruebas.

Las pruebas corren contra el Postgres real, no contra un doble: lo que se
está verificando —RLS— vive en la base. Un SQLite en memoria no probaría
nada de lo que importa aquí.
"""

import uuid
from dataclasses import dataclass

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.db.session import engine, system_scope
from app.main import app
from app.models.parking_lot import DevicePolicy, ParkingLot
from app.models.tenant import Tenant
from app.models.user import User
from app.services.tenants import crear_miembro, crear_sede, crear_tenant, sembrar_permisos

CLAVE = "prueba12345"
PIN = "246810"


@pytest.fixture(autouse=True)
async def _limpiar_pool():
    """Cierra las conexiones al final de cada prueba.

    pytest-asyncio da un event loop nuevo por prueba y las conexiones de
    asyncpg quedan atadas al loop en que nacieron; reutilizarlas en el
    siguiente falla.
    """
    yield
    await engine.dispose()


@dataclass
class TenantDePrueba:
    slug: str
    id: uuid.UUID
    admin: str
    operario: str
    sede_asignada: uuid.UUID
    sede_ajena: uuid.UUID


async def _crear_tenant_de_prueba(session, etiqueta: str) -> TenantDePrueba:
    sufijo = uuid.uuid4().hex[:8]
    slug = f"{etiqueta}-{sufijo}"
    tenant = await crear_tenant(session, slug=slug, nombre=f"Parqueadero {etiqueta}")

    s1 = await crear_sede(session, tenant=tenant, codigo="S1", nombre="Sede uno")
    s2 = await crear_sede(
        session,
        tenant=tenant,
        codigo="S2",
        nombre="Sede dos",
        device_policy=DevicePolicy.LOGIN_POR_TURNO,
    )

    admin = f"admin-{sufijo}@prueba.com.co"
    operario = f"operario-{sufijo}@prueba.com.co"
    await crear_miembro(
        session, tenant=tenant, email=admin, nombre="Admin",
        password=CLAVE, rol_codigo="tenant_admin",
    )
    await crear_miembro(
        session, tenant=tenant, email=operario, nombre="Operario",
        password=CLAVE, rol_codigo="operator", pin=PIN, sedes=[s1],
    )
    return TenantDePrueba(slug, tenant.id, admin, operario, s1.id, s2.id)


@pytest.fixture
async def dos_tenants():
    """Dos parqueaderos independientes, con sus usuarios. Se borran al final."""
    async with system_scope() as session:
        await sembrar_permisos(session)
        a = await _crear_tenant_de_prueba(session, "alfa")
        b = await _crear_tenant_de_prueba(session, "beta")

    yield a, b

    async with system_scope() as session:
        await session.execute(delete(Tenant).where(Tenant.id.in_([a.id, b.id])))
        await session.execute(
            delete(User).where(User.email.in_([a.admin, a.operario, b.admin, b.operario]))
        )


@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


# ── Utilidades ───────────────────────────────────────────────────────────

async def entrar(client: AsyncClient, slug: str, email: str, password: str = CLAVE) -> str:
    """Inicia sesión y devuelve el token de acceso."""
    r = await client.post(
        f"/api/v1/t/{slug}/auth/login", json={"email": email, "password": password}
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def cabecera(token: str) -> dict[str, str]:
    return {"authorization": f"Bearer {token}"}


async def sedes_de(session, tenant_id: uuid.UUID) -> list[ParkingLot]:
    consulta = select(ParkingLot).where(ParkingLot.tenant_id == tenant_id)
    return list((await session.scalars(consulta)).all())
