"""Dónde encontrar al dueño de una placa."""

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ContactoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    placa: str
    telefono: str | None
    correo: str | None


class ContactoIn(BaseModel):
    """Al menos uno de los dos. Lo que no venga se deja como estaba."""

    telefono: str | None = Field(default=None, min_length=7, max_length=24)
    correo: str | None = Field(default=None, min_length=5, max_length=160)

    @model_validator(mode="after")
    def hay_algo_que_guardar(self) -> "ContactoIn":
        if not (self.telefono or self.correo):
            raise ValueError("Hace falta un teléfono o un correo")
        return self
