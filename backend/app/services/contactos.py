"""A dónde se le manda el recibo de cada placa.

Es lo mínimo que hace falta para no volver a pedirlo: una placa, y el
último WhatsApp y correo que se usaron. No se guarda historial ni nombre;
el dato existe para mandarle a esa persona el recibo de su propio
vehículo.

Guardar uno no borra el otro. Quien hoy da el correo y mañana el WhatsApp
termina con los dos, y quien cambia de número no pierde su correo.
"""

import re

from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.contacto import PlateContact
from app.models.tenant import Tenant
from app.services.tickets import normalizar_placa

# Deliberadamente laxo: descarta lo que no tiene forma de correo y deja
# pasar todo lo demás. Una expresión estricta rechaza direcciones válidas
# raras, y el precio de eso lo paga un cliente que sí quería su recibo.
_FORMA_DE_CORREO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")


class TelefonoInvalido(ValueError):
    def __init__(self) -> None:
        super().__init__("Ese número de teléfono no parece válido")


class CorreoInvalido(ValueError):
    def __init__(self) -> None:
        super().__init__("Ese correo no parece válido")


class SinDondeMandarlo(ValueError):
    def __init__(self) -> None:
        super().__init__("Hace falta un teléfono o un correo")


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


def normalizar_correo(valor: str) -> str:
    """Recorta y baja a minúsculas. No valida más de lo que se puede.

    Comprobar de verdad si un correo existe es imposible sin mandarle algo;
    lo que se puede es descartar lo que ni siquiera tiene forma de correo,
    que es donde están los errores de dedo que se ven en la caseta.
    """
    limpio = (valor or "").strip().lower()
    if not _FORMA_DE_CORREO.match(limpio) or len(limpio) > 160:
        raise CorreoInvalido()
    return limpio


async def contacto_de(session: AsyncSession, *, placa: str) -> PlateContact | None:
    normalizada = normalizar_placa(placa)
    if not normalizada:
        return None
    return await session.scalar(
        select(PlateContact).where(PlateContact.placa == normalizada)
    )


async def recordar(
    session: AsyncSession,
    *,
    tenant: Tenant,
    placa: str,
    telefono: str | None = None,
    correo: str | None = None,
) -> PlateContact:
    """Guarda dónde encontrar a esa placa, pisando lo anterior de ese campo.

    Lo que no venga se queda como estaba: mandar el recibo por correo no
    tiene por qué borrar el WhatsApp que se usó la semana pasada.
    """
    normalizada = normalizar_placa(placa)
    if not normalizada:
        raise ValueError("Hace falta la placa para recordar el contacto")

    valores: dict[str, str] = {}
    if telefono is not None and telefono.strip():
        valores["telefono"] = normalizar_telefono(telefono)
    if correo is not None and correo.strip():
        valores["correo"] = normalizar_correo(correo)
    if not valores:
        raise SinDondeMandarlo()

    # UPSERT y no leer-luego-escribir: dos ingresos de la misma placa a la
    # vez chocarían contra el índice único en vez de pisarse ordenadamente.
    consulta = (
        insert(PlateContact)
        .values(tenant_id=tenant.id, placa=normalizada, **valores)
        .on_conflict_do_update(
            constraint="uq_plate_contacts_tenant_placa",
            set_=valores,
        )
        .returning(PlateContact)
    )
    contacto = (await session.scalars(consulta)).one()
    await session.flush()
    return contacto


async def olvidar(session: AsyncSession, *, placa: str) -> bool:
    """Borra el contacto de esa placa. Lo pide quien no quiere quedar guardado."""
    normalizada = normalizar_placa(placa)
    if not normalizada:
        return False
    resultado = await session.execute(
        delete(PlateContact).where(PlateContact.placa == normalizada)
    )
    return resultado.rowcount > 0
