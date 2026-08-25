"""Motor y sesiones de SQLAlchemy, con el contexto de tenant incorporado.

Hay dos formas de abrir una sesión:

* `tenant_scope(tenant_id)` — para todo lo que toca datos de un cliente.
  Cada transacción fija `app.tenant_id` y baja el rol a `zonepark_app`,
  que no es dueño de las tablas y por lo tanto **sí** queda sujeto a RLS.

* `system_scope()` — para lo que ocurre antes de saber el tenant (buscar
  un usuario por email al iniciar sesión) o por encima de él
  (administración de plataforma). Se queda como dueño y esquiva RLS,
  así que se usa en pocos sitios y bien identificados.

Dos detalles que parecen menores y no lo son:

1. `SET LOCAL` solo surte efecto dentro de una transacción. Fuera de una,
   Postgres se limita a emitir un WARNING y la consulta corre con todos
   los privilegios. Por eso el contexto se aplica en el evento
   `after_begin`, que es exactamente el momento en que hay transacción.

2. Se aplica en *cada* begin, no una sola vez al abrir la sesión. Si un
   servicio hace commit y sigue consultando, SQLAlchemy abre una
   transacción nueva; sin este enganche esa segunda transacción correría
   como dueño y sin filtro de tenant.

`SET LOCAL` además revierte al terminar la transacción, así que nada se
filtra a la siguiente petición que reutilice la conexión del pool.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import Session

from app.config import settings

APP_ROLE = "zonepark_app"

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


@event.listens_for(Session, "after_begin")
def _aplicar_contexto_de_tenant(session: Session, transaction, connection) -> None:
    """Fija el tenant y baja de rol al empezar cada transacción."""
    tenant_id = session.info.get("tenant_id")
    if tenant_id is None:
        # Sesión de sistema: sigue como dueño, fuera de RLS.
        return

    connection.execute(
        text("SELECT set_config('app.tenant_id', :tid, true)"),
        {"tid": str(tenant_id)},
    )
    # El nombre del rol no puede ir como parámetro; es una constante nuestra.
    connection.execute(text(f"SET LOCAL ROLE {APP_ROLE}"))


@asynccontextmanager
async def tenant_scope(tenant_id: uuid.UUID) -> AsyncGenerator[AsyncSession, None]:
    """Sesión sujeta a RLS y limitada a un tenant."""
    async with SessionLocal() as session:
        session.info["tenant_id"] = tenant_id
        await session.begin()
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except Exception:
            await session.rollback()
            raise


@asynccontextmanager
async def system_scope() -> AsyncGenerator[AsyncSession, None]:
    """Sesión sin tenant, fuera de RLS. Usar solo donde esté justificado."""
    async with SessionLocal() as session:
        await session.begin()
        try:
            yield session
            if session.in_transaction():
                await session.commit()
        except Exception:
            await session.rollback()
            raise
