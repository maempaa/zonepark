"""Esquemas de caja y reportes."""

import uuid
from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from app.models.caja import EstadoTurno, TipoMovimiento


class AperturaIn(BaseModel):
    parking_lot_id: uuid.UUID
    base_inicial: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    notas: str | None = Field(default=None, max_length=300)


class CierreIn(BaseModel):
    # Lo que el operario contó físicamente en el cajón.
    contado: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    notas: str | None = Field(default=None, max_length=300)


class MovimientoIn(BaseModel):
    tipo: TipoMovimiento
    concepto: str = Field(min_length=2, max_length=160)
    monto: Decimal = Field(gt=0, max_digits=14, decimal_places=2)


class MovimientoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tipo: TipoMovimiento
    concepto: str
    monto: Decimal
    created_at: datetime


class TurnoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    parking_lot_id: uuid.UUID
    membership_id: uuid.UUID
    estado: EstadoTurno
    abierto_at: datetime
    cerrado_at: datetime | None
    base_inicial: Decimal
    esperado: Decimal | None
    contado: Decimal | None
    diferencia: Decimal | None
    notas_apertura: str | None
    notas_cierre: str | None


class ArqueoOut(BaseModel):
    base_inicial: Decimal
    efectivo_cobrado: Decimal
    ingresos_manuales: Decimal
    egresos_manuales: Decimal
    esperado: Decimal
    contado: Decimal | None
    diferencia: Decimal | None
    cuadra: bool
    tickets_cobrados: int
    por_metodo: dict[str, Decimal]
    efectivo_sin_turno: Decimal


class TurnoDetalleOut(BaseModel):
    turno: TurnoOut
    arqueo: ArqueoOut
    movimientos: list[MovimientoOut]


# ── Reportes ─────────────────────────────────────────────────────────────

class FilaOcupacionOut(BaseModel):
    parking_lot_id: uuid.UUID
    sede: str
    vehicle_type_id: uuid.UUID
    tipo: str
    adentro: int


class OcupacionOut(BaseModel):
    total: int
    filas: list[FilaOcupacionOut]


class FilaDiaOut(BaseModel):
    dia: date
    tickets: int
    total: Decimal


class FilaConceptoOut(BaseModel):
    concepto: str
    tickets: int
    total: Decimal


class IngresosOut(BaseModel):
    desde: date
    hasta: date
    total: Decimal
    tickets: int
    por_dia: list[FilaDiaOut]
    por_metodo: list[FilaConceptoOut]
    por_tipo: list[FilaConceptoOut]
