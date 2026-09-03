"""El número al que se le manda el recibo de cada placa.

Es lo mínimo que hace falta para no volver a pedirlo: una placa, un
número, el último que se usó. No se guarda historial ni nombre; el dato
existe para mandarle a esa persona el recibo de su propio vehículo.
"""

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contacto import PlateContact
from app.models.tenant import Tenant
from app.services.tickets import normalizar_placa


class TelefonoInvalido(ValueError):
    def __init__(self) -> None:
        super().__init__("Ese número de teléfono no parece válido")


def normalizar_telefono(valor: str) -> str:
    """Deja los dígitos y el '+' inicial, y verifica que quede un número.

    No se impone un formato: quien teclea dicta lo que el cliente le dice,
    y un celular colombiano se dicta de varias maneras. Solo se comprueba
    que haya suficientes dígitos como para que sea un teléfono.
    """
    crudo = (valor or "").strip()
    digitos = "".join(c for c in crudo if c.isdigit())
    if not 7 <= len(digitos) <= 15:
        raise TelefonoInvalido()
    return ("+" if crudo.startswith("+") else "") + digitos


async def contacto_de(session: AsyncSession, *, placa: str) -> PlateContact | None:
    normalizada = normalizar_placa(placa)
    if not normalizada:
        return None
    return await session.scalar(
        select(PlateContact).where(PlateContact.placa == normalizada)
    )


async def recordar(
    session: AsyncSession, *, tenant: Tenant, placa: str, telefono: str
) -> PlateContact:
    """Guarda el número de esa placa, pisando el anterior si lo había."""
    normalizada = normalizar_placa(placa)
    if not normalizada:
        raise ValueError("Hace falta la placa para recordar el número")
    numero = normalizar_telefono(telefono)

    # UPSERT y no leer-luego-escribir: dos ingresos de la misma placa a la
    # vez chocarían contra el índice único en vez de pisarse ordenadamente.
    consulta = (
        insert(PlateContact)
        .values(tenant_id=tenant.id, placa=normalizada, telefono=numero)
        .on_conflict_do_update(
            constraint="uq_plate_contacts_tenant_placa",
            set_={"telefono": numero},
        )
        .returning(PlateContact)
    )
    contacto = (await session.scalars(consulta)).one()
    await session.flush()
    return contacto


async def olvidar(session: AsyncSession, *, placa: str) -> bool:
    """Borra el número de esa placa. Lo pide quien no quiere quedar guardado."""
    normalizada = normalizar_placa(placa)
    if not normalizada:
        return False
    resultado = await session.execute(
        delete(PlateContact).where(PlateContact.placa == normalizada)
    )
    return resultado.rowcount > 0
