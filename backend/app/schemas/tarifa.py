"""Esquemas de planes tarifarios y del simulador."""

import uuid
from datetime import date, datetime, time
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.domain.pricing.modelos import (
    ModoCobro,
    ModoImpuesto,
    ModoRedondeo,
    UnidadEscalon,
)
from app.models.tarifa import EstadoPlan


class FranjaIn(BaseModel):
    """Cuándo aplica la regla. 0 = lunes … 6 = domingo."""

    dias: list[int] = Field(default_factory=lambda: list(range(7)))
    desde_hora: time = time(0, 0)
    hasta_hora: time = time(0, 0)  # igual a desde_hora = todo el día
    incluye_festivos: bool = True
    solo_festivos: bool = False

    @model_validator(mode="after")
    def _dias_validos(self) -> "FranjaIn":
        if any(d < 0 or d > 6 for d in self.dias):
            raise ValueError("Los días van de 0 (lunes) a 6 (domingo)")
        if not self.dias and not self.solo_festivos:
            raise ValueError("La franja necesita al menos un día")
        return self


class EscalonIn(BaseModel):
    desde_minuto: int = Field(ge=0)
    hasta_minuto: int | None = Field(default=None, ge=1)
    precio: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    unidad: UnidadEscalon = UnidadEscalon.BLOQUE
    bloque_minutos: int = Field(default=60, ge=1)

    @model_validator(mode="after")
    def _rango_valido(self) -> "EscalonIn":
        if self.hasta_minuto is not None and self.hasta_minuto <= self.desde_minuto:
            raise ValueError("hasta_minuto debe ser mayor que desde_minuto")
        return self


class ReglaIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=48)
    vehicle_type_id: uuid.UUID
    modo: ModoCobro

    precio_minuto: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    precio_bloque: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    precio_plena: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)
    precio_dia: Decimal = Field(default=Decimal(0), ge=0, max_digits=14, decimal_places=2)

    bloque_minutos: int = Field(default=60, ge=1)
    dia_horas: int = Field(default=24, ge=1)

    gracia_minutos: int = Field(default=0, ge=0)
    cobro_minimo: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    tope_diario: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    tarifa_ticket_perdido: Decimal | None = Field(
        default=None, ge=0, max_digits=14, decimal_places=2
    )

    redondeo_modo: ModoRedondeo = ModoRedondeo.CERCANO
    redondeo_paso: int = Field(default=0, ge=0)
    impuesto_modo: ModoImpuesto = ModoImpuesto.INCLUIDO
    impuesto_tasa: Decimal = Field(default=Decimal(0), ge=0, le=1, decimal_places=4)

    franja: FranjaIn | None = None
    prioridad: int = 0
    escalones: list[EscalonIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _coherente_con_el_modo(self) -> "ReglaIn":
        """Un precio en cero casi siempre es un campo que se olvidó llenar.

        Vale más rechazarlo aquí que descubrirlo cuando el parqueadero lleve
        una semana cobrando gratis.
        """
        exigencias = {
            ModoCobro.POR_MINUTO: ("precio_minuto",),
            ModoCobro.POR_BLOQUE: ("precio_bloque",),
            ModoCobro.PRIMER_BLOQUE_LUEGO_MINUTO: ("precio_bloque", "precio_minuto"),
            ModoCobro.PLENA: ("precio_plena",),
            ModoCobro.POR_DIA: ("precio_dia",),
        }
        for campo in exigencias.get(self.modo, ()):
            if getattr(self, campo) <= 0:
                raise ValueError(f"El modo '{self.modo}' necesita {campo} mayor que cero")

        if self.modo is ModoCobro.ESCALONADO and not self.escalones:
            raise ValueError("El modo escalonado necesita al menos un escalón")
        if self.modo is not ModoCobro.ESCALONADO and self.escalones:
            raise ValueError("Solo el modo escalonado admite escalones")

        if self.escalones:
            ordenados = sorted(self.escalones, key=lambda e: e.desde_minuto)
            if ordenados[0].desde_minuto != 0:
                raise ValueError("El primer escalón debe empezar en el minuto 0")
            for previo, siguiente in zip(ordenados, ordenados[1:], strict=False):
                if previo.hasta_minuto is None:
                    raise ValueError("Solo el último escalón puede quedar sin límite")
                if previo.hasta_minuto != siguiente.desde_minuto:
                    raise ValueError(
                        f"Hay un hueco o solape entre el minuto {previo.hasta_minuto} "
                        f"y el {siguiente.desde_minuto}"
                    )
        return self


class PlanIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=32)
    nombre: str = Field(min_length=1, max_length=120)
    parking_lot_id: uuid.UUID | None = None
    vigente_desde: date | None = None
    vigente_hasta: date | None = None
    reglas: list[ReglaIn] = Field(default_factory=list)


class EscalonOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    desde_minuto: int
    hasta_minuto: int | None
    precio: Decimal
    unidad: UnidadEscalon
    bloque_minutos: int


class ReglaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    codigo: str
    vehicle_type_id: uuid.UUID
    modo: ModoCobro
    precio_minuto: Decimal
    precio_bloque: Decimal
    precio_plena: Decimal
    precio_dia: Decimal
    bloque_minutos: int
    dia_horas: int
    gracia_minutos: int
    cobro_minimo: Decimal | None
    tope_diario: Decimal | None
    # Estos dos faltaban en la salida. Sin ellos, duplicar un plan desde la
    # interfaz los borraba en silencio.
    tarifa_ticket_perdido: Decimal | None
    redondeo_modo: ModoRedondeo
    redondeo_paso: int
    impuesto_modo: ModoImpuesto
    impuesto_tasa: Decimal
    tiene_franja: bool
    franja_dias: list[int] | None
    franja_desde: time | None
    franja_hasta: time | None
    franja_incluye_festivos: bool
    franja_solo_festivos: bool
    prioridad: int
    escalones: list[EscalonOut]


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    codigo: str
    nombre: str
    version: int
    estado: EstadoPlan
    parking_lot_id: uuid.UUID | None
    vigente_desde: date | None
    vigente_hasta: date | None


class PlanDetalleOut(PlanOut):
    reglas: list[ReglaOut]


# ── Simulador ────────────────────────────────────────────────────────────

class ItemSimuladoIn(BaseModel):
    codigo: str
    cantidad: int = Field(default=1, ge=1)


class SimulacionIn(BaseModel):
    vehicle_type_id: uuid.UUID
    entrada: datetime
    salida: datetime
    items: list[ItemSimuladoIn] = Field(default_factory=list)
    parking_lot_id: uuid.UUID | None = None


class LineaOut(BaseModel):
    concepto: str
    monto: Decimal
    detalle: str | None = None


class CotizacionOut(BaseModel):
    minutos: int
    minutos_facturables: int
    lineas: list[LineaOut]
    subtotal: Decimal
    impuesto: Decimal
    ajuste_redondeo: Decimal
    total: Decimal
    regla_aplicada: str
    en_cortesia: bool
    tope_aplicado: bool
    minimo_aplicado: bool
