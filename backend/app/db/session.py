"""Motor y sesiones async de SQLAlchemy."""

from collections.abc import AsyncGenerator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_pre_ping=True,
)

SessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Dependencia de FastAPI.

    En la fase 1 esta función también ejecutará
    `SET LOCAL app.tenant_id = ...` para activar las políticas RLS.
    """
    async with SessionLocal() as session:
        yield session


# Alias para inyectar la sesión en los endpoints sin repetir Depends.
SessionDep = Annotated[AsyncSession, Depends(get_session)]
