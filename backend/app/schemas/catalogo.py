"""Esquemas de los catálogos parametrizables."""

import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class TipoVehiculoIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=32)
    nombre: str = Field(min_length=1, max_length=80)
    icono: str | None = Field(default=None, max_length=40)
    requiere_placa: bool = True
    patron_placa: str | None = Field(default=None, max_length=120)
    orden: int = 0


class TipoVehiculoPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    icono: str | None = Field(default=None, max_length=40)
    requiere_placa: bool | None = None
    patron_placa: str | None = Field(default=None, max_length=120)
    activo: bool | None = None
    orden: int | None = None


class TipoVehiculoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    codigo: str
    nombre: str
    icono: str | None
    requiere_placa: bool
    patron_placa: str | None
    activo: bool
    orden: int


class ArticuloIn(BaseModel):
    codigo: str = Field(min_length=1, max_length=32)
    nombre: str = Field(min_length=1, max_length=80)
    precio: Decimal = Field(ge=0, max_digits=14, decimal_places=2)
    orden: int = 0


class ArticuloPatch(BaseModel):
    nombre: str | None = Field(default=None, min_length=1, max_length=80)
    precio: Decimal | None = Field(default=None, ge=0, max_digits=14, decimal_places=2)
    activo: bool | None = None
    orden: int | None = None


class ArticuloOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    codigo: str
    nombre: str
    precio: Decimal
    activo: bool
    orden: int
