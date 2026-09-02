"""Lo que la pantalla de ingreso necesita para ofrecer las tarifas."""

import uuid

from pydantic import BaseModel


class OpcionIngresoOut(BaseModel):
    codigo: str
    nombre: str
    descripcion: str
    predeterminada: bool


class TarifasDeTipoOut(BaseModel):
    vehicle_type_id: uuid.UUID
    # Este tipo tiene tarifa nocturna o de festivo, así que "automática"
    # es una elección distinta de cualquiera de las fijas.
    admite_automatica: bool
    opciones: list[OpcionIngresoOut]
