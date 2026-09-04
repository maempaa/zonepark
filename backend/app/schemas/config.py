"""Datos del parqueadero que el admin edita y el cliente ve."""

from pydantic import BaseModel, ConfigDict, Field


class ConfigOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    nombre: str
    # Vacío significa "usa el de fábrica"; la pantalla muestra cuál es.
    aviso_responsabilidad: str | None
    aviso_efectivo: str
    terminos_condiciones: str | None
    terminos_efectivos: str
    timezone: str
    currency: str


class ConfigUpdate(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=160)
    aviso_responsabilidad: str | None = Field(default=None, max_length=400)
    terminos_condiciones: str | None = Field(default=None, max_length=2000)
