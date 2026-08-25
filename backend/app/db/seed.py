"""Datos iniciales.

Idempotente: se puede correr las veces que haga falta.

Crea **dos** tenants a propósito. Tener siempre un segundo parqueadero en
la base de desarrollo hace que una fuga de datos entre clientes se note
enseguida, en vez de aparecer el día que entra el segundo cliente real.
"""

import asyncio

from sqlalchemy import select

from app.db.session import system_scope
from app.models.parking_lot import DevicePolicy
from app.models.tenant import Tenant
from app.services.tenants import (
    crear_miembro,
    crear_sede,
    crear_tenant,
    provisionar_roles,
    sembrar_permisos,
)

DEMO = [
    {
        "slug": "central",
        "nombre": "Parqueadero Central",
        "razon_social": "Parqueaderos Central S.A.S.",
        "nit": "900123456-7",
        "sedes": [
            ("S1", "Sede Principal", "Calle 45 # 12-30", DevicePolicy.PIN_PERSISTENTE),
            ("S2", "Sede Norte", "Carrera 7 # 120-15", DevicePolicy.LOGIN_POR_TURNO),
        ],
        "personas": [
            ("admin@central.com.co", "Ana Admin", "central12345", "tenant_admin", None, None),
            ("super@central.com.co", "Sergio Supervisor", "central12345",
             "manager", None, ["S1"]),
            ("operario@central.com.co", "Omar Operario", "central12345",
             "operator", "482913", ["S1"]),
        ],
    },
    {
        "slug": "norte",
        "nombre": "Parqueadero del Norte",
        "razon_social": "Inversiones Norte Ltda.",
        "nit": "901987654-3",
        "sedes": [("S1", "Sede Única", "Avenida 68 # 40-10", DevicePolicy.PIN_PERSISTENTE)],
        "personas": [
            ("admin@norte.com.co", "Nora Admin", "norte12345", "tenant_admin", None, None),
        ],
    },
]


async def seed() -> None:
    async with system_scope() as session:
        total = await sembrar_permisos(session)
        print(f"Permisos sincronizados: {total}")

        for definicion in DEMO:
            tenant = await session.scalar(
                select(Tenant).where(Tenant.slug == definicion["slug"])
            )
            if tenant is None:
                tenant = await crear_tenant(
                    session,
                    slug=definicion["slug"],
                    nombre=definicion["nombre"],
                    razon_social=definicion["razon_social"],
                    nit=definicion["nit"],
                )
                print(f"\nTenant creado: {tenant.slug}")
            else:
                # Resincroniza permisos de los roles por si el catálogo creció.
                await provisionar_roles(session, tenant.id)
                print(f"\nTenant existente: {tenant.slug} (roles resincronizados)")

            sedes = {}
            for codigo, nombre, direccion, politica in definicion["sedes"]:
                existente = next(
                    (s for s in sedes.values() if s.codigo == codigo), None
                )
                if existente is None:
                    from app.models.parking_lot import ParkingLot

                    existente = await session.scalar(
                        select(ParkingLot).where(
                            ParkingLot.tenant_id == tenant.id, ParkingLot.codigo == codigo
                        )
                    )
                if existente is None:
                    existente = await crear_sede(
                        session,
                        tenant=tenant,
                        codigo=codigo,
                        nombre=nombre,
                        direccion=direccion,
                        device_policy=politica,
                    )
                sedes[codigo] = existente
                print(f"  sede {codigo}: {nombre} ({politica.value})")

            for email, nombre, password, rol, pin, codigos_sede in definicion["personas"]:
                asignadas = [sedes[c] for c in codigos_sede] if codigos_sede else None
                await crear_miembro(
                    session,
                    tenant=tenant,
                    email=email,
                    nombre=nombre,
                    password=password,
                    rol_codigo=rol,
                    pin=pin,
                    sedes=asignadas,
                )
                alcance = ", ".join(codigos_sede) if codigos_sede else "todas las sedes"
                extra = f", PIN {pin}" if pin else ""
                print(f"  {rol:13} {email:24} clave: {password}{extra} → {alcance}")

    print("\nListo. Entra en http://localhost:4321/t/central")


if __name__ == "__main__":
    asyncio.run(seed())
