"""Reportes de ocupación e ingresos."""

from datetime import UTC, date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Response, status

from app.deps import IdentidadDep, SesionDep, TenantDep, requiere
from app.schemas.caja import IngresosOut, OcupacionOut
from app.services.reportes import ingresos, ingresos_a_csv, ocupacion

router = APIRouter(prefix="/reportes", tags=["reportes"])

MAXIMO_DIAS = 400


def _rango(desde: date | None, hasta: date | None, zona: str) -> tuple[date, date]:
    """Por defecto, los últimos 30 días en la hora del tenant."""
    from zoneinfo import ZoneInfo

    hoy = datetime.now(UTC).astimezone(ZoneInfo(zona)).date()
    fin = hasta or hoy
    inicio = desde or (fin - timedelta(days=29))

    if inicio > fin:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST, "La fecha inicial es posterior a la final"
        )
    if (fin - inicio).days > MAXIMO_DIAS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"El rango no puede pasar de {MAXIMO_DIAS} días",
        )
    return inicio, fin


@router.get("/ocupacion", response_model=OcupacionOut)
async def ver_ocupacion(
    session: SesionDep,
    identidad: IdentidadDep,
    _: None = Depends(requiere("report:read")),
) -> OcupacionOut:
    """Qué hay adentro ahora mismo, por sede y tipo de vehículo."""
    filas = await ocupacion(session, sedes=identidad.sedes)
    return OcupacionOut(
        total=sum(f.adentro for f in filas),
        filas=[
            {
                "parking_lot_id": f.parking_lot_id,
                "sede": f.sede,
                "vehicle_type_id": f.vehicle_type_id,
                "tipo": f.tipo,
                "adentro": f.adentro,
            }
            for f in filas
        ],
    )


@router.get("/ingresos", response_model=IngresosOut)
async def ver_ingresos(
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    desde: date | None = None,
    hasta: date | None = None,
    _: None = Depends(requiere("report:read")),
) -> IngresosOut:
    """Lo cobrado en un rango, por día, forma de pago y tipo de vehículo."""
    inicio, fin = _rango(desde, hasta, tenant.timezone)
    datos = await ingresos(
        session, sedes=identidad.sedes, desde=inicio, hasta=fin, zona=tenant.timezone
    )
    return IngresosOut(
        desde=datos.desde,
        hasta=datos.hasta,
        total=datos.total,
        tickets=datos.tickets,
        por_dia=[{"dia": f.dia, "tickets": f.tickets, "total": f.total} for f in datos.por_dia],
        por_metodo=[
            {"concepto": f.concepto, "tickets": f.tickets, "total": f.total}
            for f in datos.por_metodo
        ],
        por_tipo=[
            {"concepto": f.concepto, "tickets": f.tickets, "total": f.total}
            for f in datos.por_tipo
        ],
    )


@router.get("/ingresos.csv")
async def exportar_ingresos(
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    desde: date | None = None,
    hasta: date | None = None,
    _: None = Depends(requiere("report:read")),
) -> Response:
    """El mismo reporte en CSV, para abrirlo en una hoja de cálculo."""
    inicio, fin = _rango(desde, hasta, tenant.timezone)
    datos = await ingresos(
        session, sedes=identidad.sedes, desde=inicio, hasta=fin, zona=tenant.timezone
    )
    nombre = f"ingresos-{tenant.slug}-{inicio}-a-{fin}.csv"
    return Response(
        content=ingresos_a_csv(datos),
        media_type="text/csv; charset=utf-8",
        headers={"content-disposition": f'attachment; filename="{nombre}"'},
    )
