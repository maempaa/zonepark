from fastapi import APIRouter

from app.api.v1 import auth, catalogo, health, meta, sedes, tarifas, tickets

# Rutas que no dependen de ningún tenant.
api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(meta.router)

# D1: el tenant viaja en la ruta. Todo lo que cuelga de aquí resuelve el
# tenant antes de tocar la base y corre bajo RLS.
tenant_router = APIRouter(prefix="/t/{tenant_slug}")
tenant_router.include_router(auth.router)
tenant_router.include_router(sedes.router)
tenant_router.include_router(catalogo.router)
tenant_router.include_router(tarifas.router)
tenant_router.include_router(tickets.router)

api_router.include_router(tenant_router)
