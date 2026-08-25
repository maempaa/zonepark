"""Punto de entrada de la API de ZonePark."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.v1 import health as health_module
from app.api.v1.router import api_router
from app.config import settings
from app.db.session import engine
from app.services.auth import CredencialesInvalidas, CuentaBloqueada, DispositivoNoAutorizado


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await engine.dispose()


app = FastAPI(
    title="ZonePark API",
    description="Administración multitenant de parqueaderos",
    version="0.2.0",
    lifespan=lifespan,
    docs_url=None if settings.is_production else "/docs",
    redoc_url=None,
)

if settings.cors_origin_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )


# ── Errores de dominio → códigos HTTP ────────────────────────────────────
# Se traducen aquí para que los servicios no tengan que saber de HTTP.

@app.exception_handler(CredencialesInvalidas)
async def _credenciales(request: Request, exc: CredencialesInvalidas) -> JSONResponse:
    return JSONResponse(
        {"detail": str(exc)},
        status_code=status.HTTP_401_UNAUTHORIZED,
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(CuentaBloqueada)
async def _bloqueada(request: Request, exc: CuentaBloqueada) -> JSONResponse:
    return JSONResponse(
        {"detail": str(exc), "bloqueada_hasta": exc.hasta.isoformat()},
        status_code=status.HTTP_429_TOO_MANY_REQUESTS,
    )


@app.exception_handler(DispositivoNoAutorizado)
async def _dispositivo(request: Request, exc: DispositivoNoAutorizado) -> JSONResponse:
    return JSONResponse({"detail": str(exc)}, status_code=status.HTTP_403_FORBIDDEN)


app.include_router(api_router, prefix="/api/v1")

# /health también en la raíz: es lo que consulta el healthcheck de docker.
app.include_router(health_module.router)
