import uuid

from pydantic import BaseModel, ConfigDict, Field

from app.models.parking_lot import DevicePolicy


class SedeIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=32)
    nombre: str = Field(min_length=1, max_length=160)
    direccion: str | None = Field(default=None, max_length=240)
    timezone: str | None = Field(default=None, max_length=64)
    device_policy: DevicePolicy = DevicePolicy.PIN_PERSISTENTE


class SedeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    codigo: str
    nombre: str
    direccion: str | None
    timezone: str | None
    device_policy: DevicePolicy
    ticket_prefix: str
    is_active: bool
