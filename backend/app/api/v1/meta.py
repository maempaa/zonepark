"""Metadatos que el frontend necesita para arrancar."""

from fastapi import APIRouter

from app.config import settings

router = APIRouter(prefix="/meta", tags=["metadatos"])


@router.get("")
async def meta() -> dict:
    return {
        "app": "ZonePark",
        "version": "0.1.0",
        "tenant_mode": settings.tenant_mode,
        "default_timezone": settings.default_timezone,
        "default_currency": settings.default_currency,
        "default_rounding_step": settings.default_rounding_step,
    }
