"""Datos iniciales.

Idempotente: se puede correr las veces que haga falta.

Crea **dos** tenants a propósito. Tener siempre un segundo parqueadero en
la base de desarrollo hace que una fuga de datos entre clientes se note
enseguida, en vez de aparecer el día que entra el segundo cliente real.
"""

import asyncio
from datetime import date, time
from decimal import Decimal

from sqlalchemy import select

from app.db.session import system_scope
from app.domain.pricing.modelos import ModoCobro, ModoRedondeo
from app.models.catalogo import Holiday, ServiceItem, VehicleType
from app.models.parking_lot import DevicePolicy
from app.models.tarifa import EstadoPlan, RatePlan, RateRule
from app.models.tenant import Tenant
from app.services.tenants import (
    crear_miembro,
    crear_sede,
    crear_tenant,
    provisionar_roles,
    sembrar_permisos,
)

# ── Catálogos y tarifas de ejemplo ───────────────────────────────────────
# Valores en el orden de magnitud de un parqueadero real de Bogotá.

TIPOS_DE_VEHICULO = [
    # (código, nombre, icono, requiere placa, orden)
    ("carro", "Carro", "car", True, 1),
    ("moto", "Moto", "motorcycle", True, 2),
    ("bicicleta", "Bicicleta", "bike", False, 3),
]

ARTICULOS = [
    ("casco", "Guarda casco", Decimal("1000.00"), 1),
    ("lavada", "Lavada", Decimal("18000.00"), 2),
    ("ticket_perdido", "Ticket perdido", Decimal("15000.00"), 3),
]

# Festivos colombianos de 2026 (los del segundo semestre bastan para probar).
FESTIVOS_2026 = [
    (date(2026, 8, 17), "Asunción de la Virgen"),
    (date(2026, 10, 12), "Día de la Raza"),
    (date(2026, 11, 2), "Día de Todos los Santos"),
    (date(2026, 11, 16), "Independencia de Cartagena"),
    (date(2026, 12, 8), "Inmaculada Concepción"),
    (date(2026, 12, 25), "Navidad"),
]


async def sembrar_catalogos_y_tarifas(session, tenant) -> None:
    """Tipos de vehículo, artículos y un plan tarifario activo.

    El plan de ejemplo muestra las tres cosas que más se piden: hora o
    fracción con tope diario, una tarifa nocturna más barata, y un tipo
    que se cobra a tarifa plena.
    """
    tipos = {}
    for codigo, nombre, icono, placa, orden in TIPOS_DE_VEHICULO:
        tipo = await session.scalar(
            select(VehicleType).where(
                VehicleType.tenant_id == tenant.id, VehicleType.codigo == codigo
            )
        )
        if tipo is None:
            tipo = VehicleType(
                tenant_id=tenant.id, codigo=codigo, nombre=nombre, icono=icono,
                requiere_placa=placa, orden=orden,
            )
            session.add(tipo)
            await session.flush()
        tipos[codigo] = tipo

    for codigo, nombre, precio, orden in ARTICULOS:
        existe = await session.scalar(
            select(ServiceItem).where(
                ServiceItem.tenant_id == tenant.id, ServiceItem.codigo == codigo
            )
        )
        if existe is None:
            session.add(ServiceItem(
                tenant_id=tenant.id, codigo=codigo, nombre=nombre,
                precio=precio, orden=orden,
            ))

    for fecha, nombre in FESTIVOS_2026:
        existe = await session.scalar(
            select(Holiday).where(Holiday.tenant_id == tenant.id, Holiday.fecha == fecha)
        )
        if existe is None:
            session.add(Holiday(tenant_id=tenant.id, fecha=fecha, nombre=nombre))

    plan = await session.scalar(
        select(RatePlan).where(RatePlan.tenant_id == tenant.id, RatePlan.codigo == "general")
    )
    if plan is not None:
        return  # ya sembrado

    plan = RatePlan(
        tenant_id=tenant.id, codigo="general", nombre="Tarifa general",
        version=1, estado=EstadoPlan.ACTIVO,
    )
    session.add(plan)
    await session.flush()

    comunes = {
        "tenant_id": tenant.id,
        "rate_plan_id": plan.id,
        "redondeo_modo": ModoRedondeo.CERCANO,
        "redondeo_paso": 50,
    }
    session.add_all([
        # Carro: hora o fracción, cortesía de 15 min, tope diario.
        RateRule(
            **comunes, vehicle_type_id=tipos["carro"].id, codigo="carro-general",
            modo=ModoCobro.POR_BLOQUE, precio_bloque=Decimal("3000.00"),
            bloque_minutos=60, gracia_minutos=15, tope_diario=Decimal("22000.00"),
        ),
        # Carro de noche: más barato, de 8 p.m. a 6 a.m.
        RateRule(
            **comunes, vehicle_type_id=tipos["carro"].id, codigo="carro-nocturna",
            modo=ModoCobro.POR_BLOQUE, precio_bloque=Decimal("2000.00"),
            bloque_minutos=60, gracia_minutos=15, tope_diario=Decimal("22000.00"),
            tiene_franja=True, franja_dias=list(range(7)),
            franja_desde=time(20, 0), franja_hasta=time(6, 0), prioridad=10,
        ),
        # Moto: media hora o fracción.
        RateRule(
            **comunes, vehicle_type_id=tipos["moto"].id, codigo="moto-general",
            modo=ModoCobro.POR_BLOQUE, precio_bloque=Decimal("900.00"),
            bloque_minutos=30, gracia_minutos=15, tope_diario=Decimal("12000.00"),
        ),
        # Bicicleta: precio único por estadía.
        RateRule(
            **comunes, vehicle_type_id=tipos["bicicleta"].id, codigo="bici-general",
            modo=ModoCobro.PLENA, precio_plena=Decimal("2000.00"), gracia_minutos=30,
        ),
    ])
    await session.flush()

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

            await sembrar_catalogos_y_tarifas(session, tenant)
            print("  tarifas: carro $3.000/h (noche $2.000, tope $22.000), "
                  "moto $900 media hora, bici $2.000 plena")

    print("\nListo. Entra en http://localhost:4321/t/central")


if __name__ == "__main__":
    asyncio.run(seed())
