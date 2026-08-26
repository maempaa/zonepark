"""Congelado de tarifas en el ticket.

La propiedad que importa: lo que se guarda al abrir el ticket tiene que
reconstruirse idéntico. Si la ida y vuelta pierde algo, un recálculo
posterior cobraría distinto de lo que se le prometió al cliente.
"""

import json
from datetime import time, timedelta
from decimal import Decimal

import pytest

from app.domain.pricing.modelos import (
    Escalon,
    Franja,
    ModoCobro,
    ModoImpuesto,
    ModoRedondeo,
    ReglaTarifaria,
    UnidadEscalon,
)
from app.domain.pricing.motor import cotizar
from app.domain.pricing.snapshot import (
    congelar,
    descongelar,
    deserializar,
    serializar,
)

from .test_tarifas import BOGOTA, momento

REGLAS_DE_MUESTRA = [
    ReglaTarifaria(
        codigo="simple", modo=ModoCobro.POR_BLOQUE,
        precio_bloque=Decimal("3000.00"), bloque_minutos=60,
    ),
    ReglaTarifaria(
        codigo="con-todo",
        modo=ModoCobro.PRIMER_BLOQUE_LUEGO_MINUTO,
        precio_bloque=Decimal("3500.50"),
        precio_minuto=Decimal("58.33"),
        bloque_minutos=45,
        gracia_minutos=10,
        cobro_minimo=Decimal("2000.00"),
        tope_diario=Decimal("22000.00"),
        tarifa_ticket_perdido=Decimal("15000.00"),
        redondeo_modo=ModoRedondeo.ARRIBA,
        redondeo_paso=100,
        impuesto_modo=ModoImpuesto.AGREGADO,
        impuesto_tasa=Decimal("0.1900"),
        prioridad=7,
    ),
    ReglaTarifaria(
        codigo="escalonada",
        modo=ModoCobro.ESCALONADO,
        escalones=(
            Escalon(0, 60, Decimal("3000.00"), UnidadEscalon.FIJO),
            Escalon(60, 480, Decimal("2000.00"), UnidadEscalon.BLOQUE, bloque_minutos=60),
            Escalon(480, None, Decimal("25.00"), UnidadEscalon.MINUTO),
        ),
        tope_diario=Decimal("20000.00"),
    ),
    ReglaTarifaria(
        codigo="nocturna",
        modo=ModoCobro.POR_BLOQUE,
        precio_bloque=Decimal("1500.00"),
        franja=Franja(
            dias=frozenset({0, 1, 2, 3, 4}),
            desde_hora=time(20, 0),
            hasta_hora=time(6, 0),
            incluye_festivos=False,
        ),
        prioridad=10,
    ),
    ReglaTarifaria(
        codigo="festiva",
        modo=ModoCobro.PLENA,
        precio_plena=Decimal("18000.00"),
        franja=Franja(solo_festivos=True),
        prioridad=99,
    ),
]


@pytest.mark.parametrize("regla", REGLAS_DE_MUESTRA, ids=lambda r: r.codigo)
def test_la_ida_y_vuelta_devuelve_la_regla_identica(regla):
    # Pasa por JSON de verdad, no solo por dict: así se detecta cualquier
    # tipo que no sea serializable.
    recuperada = deserializar(json.loads(json.dumps(serializar(regla))))
    assert recuperada == regla


def test_los_decimales_no_pierden_precision():
    """Si los precios pasaran por float, aquí aparecerían los céntimos perdidos."""
    regla = ReglaTarifaria(
        codigo="fino", modo=ModoCobro.POR_MINUTO, precio_minuto=Decimal("33.33"),
        impuesto_tasa=Decimal("0.1900"),
    )
    recuperada = deserializar(json.loads(json.dumps(serializar(regla))))
    assert recuperada.precio_minuto == Decimal("33.33")
    assert str(recuperada.precio_minuto) == "33.33"
    assert recuperada.impuesto_tasa == Decimal("0.1900")


def test_el_snapshot_completo_cotiza_igual_que_el_original():
    """La prueba que de verdad importa: mismo dinero antes y después."""
    entrada = momento(24, 19)
    salida = momento(25, 7)

    original = cotizar(reglas=REGLAS_DE_MUESTRA[3:4] + REGLAS_DE_MUESTRA[0:1],
                       entrada=entrada, salida=salida, zona=BOGOTA)

    snapshot = json.loads(json.dumps(
        congelar(REGLAS_DE_MUESTRA[3:4] + REGLAS_DE_MUESTRA[0:1],
                 plan_codigo="general", plan_version=3)
    ))
    recuperado = cotizar(reglas=descongelar(snapshot),
                         entrada=entrada, salida=salida, zona=BOGOTA)

    assert recuperado.total == original.total
    assert recuperado.lineas == original.lineas


def test_el_snapshot_guarda_de_que_plan_y_version_vino():
    snapshot = congelar(REGLAS_DE_MUESTRA[:1], plan_codigo="general", plan_version=4)
    assert snapshot["plan_codigo"] == "general"
    assert snapshot["plan_version"] == 4
    assert snapshot["version_snapshot"] == 1


def test_un_snapshot_de_otra_version_falla_en_vez_de_adivinar():
    """Peor que no poder leerlo sería leerlo mal y cobrar cualquier cosa."""
    snapshot = congelar(REGLAS_DE_MUESTRA[:1], plan_codigo="g", plan_version=1)
    snapshot["version_snapshot"] = 99
    with pytest.raises(ValueError, match="versión"):
        descongelar(snapshot)


def test_subir_la_tarifa_no_altera_un_ticket_ya_abierto():
    """El escenario real que justifica todo este módulo."""
    entrada = momento(24, 8)
    salida = entrada + timedelta(hours=3)

    vieja = ReglaTarifaria(codigo="carro", modo=ModoCobro.POR_BLOQUE,
                           precio_bloque=Decimal("3000.00"))
    congelada = json.loads(json.dumps(congelar([vieja], plan_codigo="g", plan_version=1)))

    # El parqueadero sube la tarifa mientras el carro sigue adentro.
    nueva = ReglaTarifaria(codigo="carro", modo=ModoCobro.POR_BLOQUE,
                           precio_bloque=Decimal("5000.00"))

    al_salir = cotizar(reglas=descongelar(congelada), entrada=entrada, salida=salida, zona=BOGOTA)
    con_la_nueva = cotizar(reglas=[nueva], entrada=entrada, salida=salida, zona=BOGOTA)

    assert al_salir.total == Decimal(9000), "se le cobró la tarifa nueva a un ticket viejo"
    assert con_la_nueva.total == Decimal(15000)
