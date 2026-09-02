from fastapi import APIRouter

from app.api.v1 import (
    admin,
    auth,
    caja,
    catalogo,
    config,
    health,
    meta,
    publico,
    reportes,
    sedes,
    tarifas,
    tarifas_ingreso,
    tickets,
)

# Rutas que no dependen de ningún tenant.
api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(meta.router)

# Plataforma: fuera del prefijo de tenant, porque quien la usa no pertenece
# a ninguno.
api_router.include_router(admin.router)

# D1: el tenant viaja en la ruta. Todo lo que cuelga de aquí resuelve el
# tenant antes de tocar la base y corre bajo RLS.
tenant_router = APIRouter(prefix="/t/{tenant_slug}")
tenant_router.include_router(auth.router)
# Sin sesión: lo abre el cliente con el enlace de su ticket.
tenant_router.include_router(publico.router)
tenant_router.include_router(sedes.router)
tenant_router.include_router(config.router)
tenant_router.include_router(catalogo.router)
tenant_router.include_router(tarifas.router)
tenant_router.include_router(tarifas_ingreso.router)
tenant_router.include_router(tickets.router)
tenant_router.include_router(caja.router)
tenant_router.include_router(reportes.router)

api_router.include_router(tenant_router)
