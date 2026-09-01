"""Lo que se publica del recibo. Ni un campo más.

Este esquema no hereda ni reutiliza el del operario a propósito: son dos
públicos distintos y lo que se agregue allá no debe aparecer aquí solo
por compartir una clase.
"""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class LineaReciboOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    concepto: str
    detalle: str | None
    monto: Decimal


class ReciboPublicoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    parqueadero: str
    sede: str
    direccion: str | None
    telefono: str | None
    aviso: str

    codigo: str
    placa: str | None
    vehiculo: str
    entrada_at: datetime
    salida_at: datetime | None
    estado: str

    minutos: int
    lineas: list[LineaReciboOut]
    total: Decimal
    tarifa: str | None
    estimado: bool
    en_cortesia: bool

    calculado_at: datetime
