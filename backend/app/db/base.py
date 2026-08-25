"""Clase base de los modelos. Todos los modelos deben importarse aquí
para que Alembic los vea al autogenerar migraciones."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Los modelos se irán registrando aquí en la fase 1.
