"""Turnos de caja y arqueo."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import IdentidadDep, SesionDep, TenantDep, requiere
from app.models.caja import CashShift
from app.models.parking_lot import ParkingLot
from app.schemas.caja import (
    AperturaIn,
    ArqueoOut,
    CierreIn,
    MovimientoIn,
    MovimientoOut,
    TurnoDetalleOut,
    TurnoOut,
)
from app.services import audit
from app.services.caja import (
    Arqueo,
    TurnoNoOperable,
    TurnoYaAbierto,
    abrir_turno,
    calcular_arqueo,
    cerrar_turno,
    registrar_movimiento,
    turno_abierto_de,
)
from app.services.reportes import turnos_del_rango

router = APIRouter(prefix="/caja", tags=["caja"])


def _arqueo_out(a: Arqueo) -> ArqueoOut:
    return ArqueoOut(
        base_inicial=a.base_inicial,
        efectivo_cobrado=a.efectivo_cobrado,
        ingresos_manuales=a.ingresos_manuales,
        egresos_manuales=a.egresos_manuales,
        esperado=a.esperado,
        contado=a.contado,
        diferencia=a.diferencia,
        cuadra=a.cuadra,
        tickets_cobrados=a.tickets_cobrados,
        por_metodo=a.por_metodo,
        efectivo_sin_turno=a.efectivo_sin_turno,
    )


async def _turno_o_404(session: AsyncSession, turno_id: uuid.UUID) -> CashShift:
    turno = await session.get(CashShift, turno_id)
    if turno is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe ese turno")
    return turno


def _verificar_alcance(identidad, parking_lot_id: uuid.UUID) -> None:
    if not identidad.alcanza_sede(parking_lot_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esa sede no está en tu alcance")


async def _detalle(session: AsyncSession, turno: CashShift) -> TurnoDetalleOut:
    arqueo = await calcular_arqueo(session, turno=turno)
    return TurnoDetalleOut(
        turno=TurnoOut.model_validate(turno),
        arqueo=_arqueo_out(arqueo),
        movimientos=[MovimientoOut.model_validate(m) for m in turno.movimientos],
    )


# ── Turno propio ─────────────────────────────────────────────────────────

@router.get("/mi-turno", response_model=TurnoDetalleOut | None)
async def mi_turno(
    session: SesionDep,
    identidad: IdentidadDep,
    parking_lot_id: uuid.UUID,
    _: None = Depends(requiere("cash:operate")),
) -> TurnoDetalleOut | None:
    """El turno abierto del operario en esa sede, si tiene alguno."""
    _verificar_alcance(identidad, parking_lot_id)
    if identidad.membership_id is None:
        return None

    turno = await turno_abierto_de(
        session, parking_lot_id=parking_lot_id, membership_id=identidad.membership_id
    )
    return None if turno is None else await _detalle(session, turno)


@router.post("/abrir", response_model=TurnoDetalleOut, status_code=status.HTTP_201_CREATED)
async def abrir(
    datos: AperturaIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("cash:operate")),
) -> TurnoDetalleOut:
    _verificar_alcance(identidad, datos.parking_lot_id)
    if identidad.membership_id is None:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tu sesión no tiene membresía")

    sede = await session.get(ParkingLot, datos.parking_lot_id)
    if sede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe esa sede")

    try:
        turno = await abrir_turno(
            session,
            tenant=tenant,
            sede=sede,
            membership_id=identidad.membership_id,
            base_inicial=datos.base_inicial,
            ahora=datetime.now(UTC),
            notas=datos.notas,
        )
    except TurnoYaAbierto as e:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {"detail": str(e), "turno_abierto": str(e.turno.id)},
        ) from e

    await audit.registrar(
        session, accion="caja.abrir", entidad="cash_shift", entidad_id=turno.id,
        tenant_id=tenant.id, actor_user_id=identidad.user_id,
        despues={"base_inicial": str(turno.base_inicial)}, request=request,
    )
    return await _detalle(session, turno)


@router.post("/{turno_id}/movimientos", response_model=TurnoDetalleOut)
async def mover(
    turno_id: uuid.UUID,
    datos: MovimientoIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("cash:operate")),
) -> TurnoDetalleOut:
    """Registra un ingreso o egreso de efectivo ajeno a los tickets."""
    turno = await _turno_o_404(session, turno_id)
    _verificar_alcance(identidad, turno.parking_lot_id)

    try:
        await registrar_movimiento(
            session, tenant=tenant, turno=turno, tipo=datos.tipo,
            concepto=datos.concepto, monto=datos.monto,
            membership_id=identidad.membership_id,
        )
    except TurnoNoOperable as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    await audit.registrar(
        session, accion="caja.movimiento", entidad="cash_shift", entidad_id=turno.id,
        tenant_id=tenant.id, actor_user_id=identidad.user_id,
        despues={"tipo": datos.tipo.value, "concepto": datos.concepto,
                 "monto": str(datos.monto)},
        request=request,
    )
    return await _detalle(session, turno)


@router.post("/{turno_id}/cerrar", response_model=TurnoDetalleOut)
async def cerrar(
    turno_id: uuid.UUID,
    datos: CierreIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("cash:operate")),
) -> TurnoDetalleOut:
    """Cierra el turno con el conteo físico y congela el arqueo."""
    turno = await _turno_o_404(session, turno_id)
    _verificar_alcance(identidad, turno.parking_lot_id)

    try:
        arqueo = await cerrar_turno(
            session, turno=turno, contado=datos.contado,
            ahora=datetime.now(UTC), notas=datos.notas,
        )
    except TurnoNoOperable as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    await audit.registrar(
        session, accion="caja.cerrar", entidad="cash_shift", entidad_id=turno.id,
        tenant_id=tenant.id, actor_user_id=identidad.user_id,
        despues={"esperado": str(arqueo.esperado), "contado": str(arqueo.contado),
                 "diferencia": str(arqueo.diferencia)},
        request=request,
    )
    await session.refresh(turno)
    return TurnoDetalleOut(
        turno=TurnoOut.model_validate(turno),
        arqueo=_arqueo_out(arqueo),
        movimientos=[MovimientoOut.model_validate(m) for m in turno.movimientos],
    )


# ── Consulta ─────────────────────────────────────────────────────────────

@router.get("/turnos", response_model=list[TurnoOut])
async def listar_turnos(
    session: SesionDep,
    identidad: IdentidadDep,
    solo_abiertos: bool = False,
    limite: int = 100,
    _: None = Depends(requiere("cash:read")),
) -> list[CashShift]:
    return await turnos_del_rango(
        session, sedes=identidad.sedes, solo_abiertos=solo_abiertos, limite=min(limite, 500)
    )


@router.get("/turnos/{turno_id}", response_model=TurnoDetalleOut)
async def ver_turno(
    turno_id: uuid.UUID,
    session: SesionDep,
    identidad: IdentidadDep,
    _: None = Depends(requiere("cash:read")),
) -> TurnoDetalleOut:
    turno = await _turno_o_404(session, turno_id)
    _verificar_alcance(identidad, turno.parking_lot_id)
    return await _detalle(session, turno)


@router.get("/descuadres", response_model=list[TurnoOut])
async def listar_descuadres(
    session: SesionDep,
    identidad: IdentidadDep,
    limite: int = 20,
    _: None = Depends(requiere("cash:read")),
) -> list[CashShift]:
    """Turnos cerrados que no cuadraron, del más grande al más pequeño."""
    from app.services.reportes import descuadres

    return await descuadres(session, sedes=identidad.sedes, limite=min(limite, 100))
