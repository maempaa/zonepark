"""Datos iniciales. Se llena en la fase 1 (roles, permisos, tenant de demo)."""

import asyncio

from app.db.session import SessionLocal


async def seed() -> None:
    async with SessionLocal() as session:  # noqa: F841
        print("Nada que sembrar todavía — llega en la fase 1.")


if __name__ == "__main__":
    asyncio.run(seed())
