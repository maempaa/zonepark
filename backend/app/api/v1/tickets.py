"""Operación: ingresos, cotización, cobro y anulaciones."""

import uuid
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.deps import IdentidadDep, SesionDep, TenantDep, requiere
from app.domain.pricing.modelos import Cotizacion
from app.models.catalogo import ServiceItem, VehicleType
from app.models.parking_lot import ParkingLot
from app.models.ticket import EstadoTicket, Ticket
from app.schemas.tarifa import CotizacionOut
from app.schemas.ticket import (
    AnulacionIn,
    CobroIn,
    CotizacionConOpcionesOut,
    IngresoIn,
    ItemIn,
    ReciboOut,
    TicketDetalleOut,
    TicketOut,
)
from app.services import audit
from app.services.tarifas import SinPlanVigente, SinTarifaParaElVehiculo
from app.services.tickets import (
    MotivoRequerido,
    OpcionDesconocida,
    PagoInsuficiente,
    PlacaConTicketAbierto,
    PlacaInvalida,
    TicketNoOperable,
    abrir_ticket,
    agregar_item,
    anular_ticket,
    buscar_tickets,
    cerrar_ticket,
    opciones_de_cobro,
)

router = APIRouter(prefix="/tickets", tags=["operación"])


def _cotizacion_out(c: Cotizacion) -> CotizacionOut:
    return CotizacionOut(
        minutos=c.minutos,
        minutos_facturables=c.minutos_facturables,
        lineas=[
            {"concepto": linea.concepto, "monto": linea.monto, "detalle": linea.detalle}
            for linea in c.lineas
        ],
        subtotal=c.subtotal,
        impuesto=c.impuesto,
        ajuste_redondeo=c.ajuste_redondeo,
        total=c.total,
        regla_aplicada=c.regla_aplicada,
        en_cortesia=c.en_cortesia,
        tope_aplicado=c.tope_aplicado,
        minimo_aplicado=c.minimo_aplicado,
    )


def _detalle(ticket: Ticket) -> TicketDetalleOut:
    snapshot = ticket.rate_snapshot or {}
    return TicketDetalleOut(
        **TicketOut.model_validate(ticket).model_dump(),
        token_publico=ticket.token_publico,
        codigo_verificacion=ticket.codigo_verificacion,
        items=list(ticket.items),
        anulacion_motivo=ticket.anulacion_motivo,
        plan_codigo=snapshot.get("plan_codigo"),
        plan_version=snapshot.get("plan_version"),
    )


async def _ticket_o_404(session: AsyncSession, ticket_id: uuid.UUID) -> Ticket:
    ticket = await session.get(Ticket, ticket_id)
    if ticket is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe ese ticket")
    return ticket


def _verificar_alcance(identidad, parking_lot_id: uuid.UUID) -> None:
    if not identidad.alcanza_sede(parking_lot_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Esa sede no está en tu alcance")


# ── Ingreso ──────────────────────────────────────────────────────────────

@router.post("", response_model=TicketDetalleOut, status_code=status.HTTP_201_CREATED)
async def registrar_ingreso(
    datos: IngresoIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("ticket:create")),
) -> TicketDetalleOut:
    """Abre un ticket. Es la pantalla que más se usa: tiene que ser rápida."""
    _verificar_alcance(identidad, datos.parking_lot_id)

    sede = await session.get(ParkingLot, datos.parking_lot_id)
    if sede is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe esa sede")
    tipo = await session.get(VehicleType, datos.vehicle_type_id)
    if tipo is None or not tipo.activo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "No existe ese tipo de vehículo")

    try:
        ticket = await abrir_ticket(
            session,
            tenant=tenant,
            sede=sede,
            tipo=tipo,
            placa=datos.placa,
            entrada=datetime.now(UTC),
            membership_id=identidad.membership_id,
            forzar=datos.forzar,
            observaciones=datos.observaciones,
            opcion_cobro=datos.opcion_cobro,
        )
    except OpcionDesconocida as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from e
    except PlacaConTicketAbierto as e:
        # D6: se advierte con el ticket existente para que el operario
        # decida si fue un error de digitación o son dos vehículos.
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "detail": str(e),
                "ticket_abierto": TicketOut.model_validate(e.ticket).model_dump(mode="json"),
            },
        ) from e
    except PlacaInvalida as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except (SinPlanVigente, SinTarifaParaElVehiculo) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    # Misma transacción que la apertura: si un artículo no existe, la
    # excepción deshace también el ticket y no queda nada a medias.
    if datos.items:
        catalogo = {
            a.codigo: a
            for a in (
                await session.scalars(
                    select(ServiceItem).where(
                        ServiceItem.codigo.in_([i.codigo for i in datos.items]),
                        ServiceItem.activo.is_(True),
                    )
                )
            ).all()
        }
        for pedido in datos.items:
            articulo = catalogo.get(pedido.codigo)
            if articulo is None:
                raise HTTPException(
                    status.HTTP_400_BAD_REQUEST, f"No existe el artículo '{pedido.codigo}'"
                )
            await agregar_item(
                session, tenant=tenant, ticket=ticket, articulo=articulo,
                cantidad=pedido.cantidad,
            )

    await audit.registrar(
        session, accion="ticket.open", entidad="ticket", entidad_id=ticket.id,
        tenant_id=tenant.id, actor_user_id=identidad.user_id,
        despues={
            "codigo": ticket.codigo,
            "placa": ticket.placa,
            "items": [i.codigo for i in datos.items],
        },
        request=request,
    )
    return _detalle(ticket)


# ── Búsqueda ─────────────────────────────────────────────────────────────

@router.get("", response_model=list[TicketOut])
async def listar_tickets(
    session: SesionDep,
    identidad: IdentidadDep,
    estado: EstadoTicket | None = EstadoTicket.ABIERTO,
    placa: str | None = None,
    limite: int = 50,
    _: None = Depends(requiere("ticket:read")),
) -> list[Ticket]:
    """Búsqueda por placa parcial: en la caseta se teclean los últimos dígitos."""
    return await buscar_tickets(
        session, sedes=identidad.sedes, estado=estado, placa=placa, limite=min(limite, 200)
    )


@router.get("/{ticket_id}", response_model=TicketDetalleOut)
async def ver_ticket(
    ticket_id: uuid.UUID,
    session: SesionDep,
    identidad: IdentidadDep,
    _: None = Depends(requiere("ticket:read")),
) -> TicketDetalleOut:
    ticket = await _ticket_o_404(session, ticket_id)
    _verificar_alcance(identidad, ticket.parking_lot_id)
    return _detalle(ticket)


# ── Artículos ────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/items", response_model=TicketDetalleOut)
async def añadir_item(
    ticket_id: uuid.UUID,
    datos: ItemIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    _: None = Depends(requiere("ticket:create")),
) -> TicketDetalleOut:
    ticket = await _ticket_o_404(session, ticket_id)
    _verificar_alcance(identidad, ticket.parking_lot_id)

    articulo = await session.scalar(
        select(ServiceItem).where(ServiceItem.codigo == datos.codigo)
    )
    if articulo is None or not articulo.activo:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No existe el artículo '{datos.codigo}'")

    try:
        await agregar_item(
            session, tenant=tenant, ticket=ticket, articulo=articulo, cantidad=datos.cantidad
        )
    except TicketNoOperable as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    return _detalle(ticket)


# ── Cotizar sin cerrar ───────────────────────────────────────────────────

@router.get("/{ticket_id}/cotizar", response_model=CotizacionConOpcionesOut)
async def cotizar(
    ticket_id: uuid.UUID,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    en: datetime | None = None,
    _: None = Depends(requiere("ticket:read")),
) -> CotizacionOut:
    """Lo que costaría salir ahora. No modifica nada.

    `en` permite proyectar a otro instante —"¿cuánto si sale en media
    hora?"— y es lo que alimenta el contador en vivo de la pantalla.
    """
    ticket = await _ticket_o_404(session, ticket_id)
    _verificar_alcance(identidad, ticket.parking_lot_id)

    momento = en or datetime.now(UTC)
    if momento.tzinfo is None:
        momento = momento.replace(tzinfo=UTC)

    try:
        opciones = await opciones_de_cobro(
            session, tenant=tenant, ticket=ticket, ahora=momento
        )
    except TicketNoOperable as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e

    recomendada = opciones[0]
    return CotizacionConOpcionesOut(
        **_cotizacion_out(recomendada.cotizacion).model_dump(),
        opciones=[
            {
                "codigo": o.codigo,
                "nombre": o.nombre,
                "recomendada": o.recomendada,
                "cotizacion": _cotizacion_out(o.cotizacion),
            }
            for o in opciones
        ],
    )


# ── Cobrar ───────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/cobrar", response_model=ReciboOut)
async def cobrar(
    ticket_id: uuid.UUID,
    datos: CobroIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    respuesta: Response,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    _: None = Depends(requiere("ticket:checkout")),
) -> ReciboOut:
    """Cierra el ticket y cobra.

    Es idempotente: si el operario reintenta porque no vio la respuesta, se
    devuelve el mismo recibo en lugar de cobrar otra vez.
    """
    ticket = await _ticket_o_404(session, ticket_id)
    _verificar_alcance(identidad, ticket.parking_lot_id)

    try:
        ticket, pago, reintento = await cerrar_ticket(
            session,
            tenant=tenant,
            ticket_id=ticket_id,
            metodo=datos.metodo,
            ahora=datetime.now(UTC),
            membership_id=identidad.membership_id,
            recibido=datos.recibido,
            referencia=datos.referencia,
            idempotency_key=idempotency_key,
            opcion=datos.opcion,
            monto_manual=datos.monto_manual,
            motivo_ajuste=datos.motivo_ajuste,
        )
    except (PagoInsuficiente, OpcionDesconocida, MotivoRequerido) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except TicketNoOperable as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    # El desglose sale de lo que quedó guardado en los cargos, no de
    # recalcular: si hubo ajuste manual, recalcular daría otra cosa.
    await session.refresh(ticket)
    cotizacion = CotizacionOut(
        minutos=int((ticket.salida_at - ticket.entrada_at).total_seconds() // 60),
        minutos_facturables=int((ticket.salida_at - ticket.entrada_at).total_seconds() // 60),
        lineas=[
            {"concepto": c.concepto, "monto": c.monto, "detalle": c.detalle}
            for c in ticket.cargos
        ],
        subtotal=pago.subtotal,
        impuesto=pago.impuesto,
        ajuste_redondeo=Decimal("0.00"),
        total=pago.monto,
        regla_aplicada=pago.regla_aplicada or "",
        en_cortesia=pago.monto == 0,
        tope_aplicado=False,
        minimo_aplicado=False,
    )

    if not reintento:
        respuesta.status_code = status.HTTP_201_CREATED
        await audit.registrar(
            session, accion="ticket.checkout", entidad="ticket", entidad_id=ticket.id,
            tenant_id=tenant.id, actor_user_id=identidad.user_id,
            despues={"codigo": ticket.codigo, "total": str(pago.monto),
                     "metodo": pago.metodo.value},
            request=request,
        )

    return ReciboOut(
        ticket=TicketOut.model_validate(ticket),
        cotizacion=_cotizacion_out(cotizacion),
        pago=pago,
        reintento=reintento,
    )


# ── Anular ───────────────────────────────────────────────────────────────

@router.post("/{ticket_id}/anular", response_model=TicketDetalleOut)
async def anular(
    ticket_id: uuid.UUID,
    datos: AnulacionIn,
    tenant: TenantDep,
    session: SesionDep,
    identidad: IdentidadDep,
    request: Request,
    _: None = Depends(requiere("ticket:void")),
) -> TicketDetalleOut:
    ticket = await _ticket_o_404(session, ticket_id)
    _verificar_alcance(identidad, ticket.parking_lot_id)

    try:
        ticket = await anular_ticket(
            session, ticket_id=ticket_id, motivo=datos.motivo,
            membership_id=identidad.membership_id,
        )
    except TicketNoOperable as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e

    await audit.registrar(
        session, accion="ticket.void", entidad="ticket", entidad_id=ticket.id,
        tenant_id=tenant.id, actor_user_id=identidad.user_id,
        despues={"codigo": ticket.codigo, "motivo": datos.motivo}, request=request,
    )
    await session.refresh(ticket)
    return _detalle(ticket)
