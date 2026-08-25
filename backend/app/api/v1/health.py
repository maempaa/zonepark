"""Sondas de salud. Las usa el healthcheck de docker y el tablero de Astro."""

from fastapi import APIRouter
from sqlalchemy import text

from app.config import settings
from app.db.session import system_scope

router = APIRouter(tags=["salud"])


@router.get("/health")
async def health() -> dict:
    """Liveness + readiness: si la base no responde, el servicio no está listo."""
    try:
        async with system_scope() as session:
            await session.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        db_ok = False

    return {
        "status": "ok" if db_ok else "degraded",
        "service": "zonepark-api",
        "env": settings.app_env,
        "database": "ok" if db_ok else "sin conexión",
    }
