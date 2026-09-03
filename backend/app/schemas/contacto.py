"""El teléfono asociado a una placa."""

from pydantic import BaseModel, ConfigDict, Field


class ContactoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    placa: str
    telefono: str


class ContactoIn(BaseModel):
    telefono: str = Field(min_length=7, max_length=24)
