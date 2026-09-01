"""Lo que se sirve sin sesión.

Todo lo que cuelgue de aquí lo puede abrir cualquiera que tenga el enlace.
Antes de agregar una ruta a este módulo: lo que devuelva es público.

Sigue bajo RLS —el tenant se resuelve por el slug de la ruta, igual que en
el resto de la aplicación—, así que un token de un parqueadero no puede
alcanzar los datos de otro ni por error de programación.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Path, status

from app.deps import SesionDep, TenantDep
from app.schemas.recibo import ReciboPublicoOut
from app.services.recibo import ReciboNoEncontrado, recibo_publico

router = APIRouter(prefix="/publico", tags=["publico"])


@router.get("/recibo/{token}", response_model=ReciboPublicoOut)
async def ver_recibo(
    tenant: TenantDep,
    session: SesionDep,
    token: str = Path(min_length=32, max_length=32, pattern=r"^[0-9a-f]{32}$"),
):
    """El recibo en vivo de un ticket. La única credencial es el token."""
    try:
        return await recibo_publico(
            session, tenant=tenant, token=token, ahora=datetime.now(UTC)
        )
    except ReciboNoEncontrado as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(e)) from e
