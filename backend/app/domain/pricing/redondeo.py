"""Redondeo de dinero a múltiplos utilizables en efectivo."""

from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.domain.pricing.modelos import ModoRedondeo

CENTAVOS = Decimal("0.01")

_MODOS = {
    ModoRedondeo.ARRIBA: ROUND_CEILING,
    ModoRedondeo.ABAJO: ROUND_FLOOR,
    ModoRedondeo.CERCANO: ROUND_HALF_UP,
}


def a_centavos(valor: Decimal) -> Decimal:
    """Normaliza a dos decimales. Todo lo que sale del motor pasa por aquí."""
    return valor.quantize(CENTAVOS, rounding=ROUND_HALF_UP)


def redondear(valor: Decimal, modo: ModoRedondeo, paso: int) -> Decimal:
    """Lleva el valor al múltiplo de `paso` más conveniente.

    En Colombia lo habitual es redondear a $50 o $100: no existen monedas
    para cobrar $4.131. `paso` en cero desactiva el redondeo.
    """
    if paso <= 0:
        return a_centavos(valor)

    unidad = Decimal(paso)
    veces = (valor / unidad).to_integral_value(rounding=_MODOS[modo])
    return a_centavos(veces * unidad)
