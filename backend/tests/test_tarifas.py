"""Motor de tarifas.

Casos tomados de cómo cobran los parqueaderos de verdad. Cada prueba fija
una regla de negocio concreta; si alguna se pone en rojo, hay dinero mal
cobrado.

El motor es puro: no toca base de datos ni servidor.
"""

from datetime import datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.domain.pricing.modelos import (
    Escalon,
    Franja,
    ItemCobrado,
    ModoCobro,
    ModoImpuesto,
    ModoRedondeo,
    ReglaTarifaria,
    UnidadEscalon,
)
from app.domain.pricing.motor import SalidaAntesDeEntrada, cotizar

BOGOTA = ZoneInfo("America/Bogota")


def momento(dia: int, hora: int, minuto: int = 0, mes: int = 8, anio: int = 2026) -> datetime:
    """Un instante en hora de Bogotá. 2026-08-24 es lunes."""
    return datetime(anio, mes, dia, hora, minuto, tzinfo=BOGOTA)


def regla(**cambios) -> ReglaTarifaria:
    base = {
        "codigo": "carro",
        "modo": ModoCobro.POR_BLOQUE,
        "precio_bloque": Decimal(3000),
        "bloque_minutos": 60,
    }
    return ReglaTarifaria(**{**base, **cambios})


# ── Hora o fracción: el caso que usa casi todo el mundo ──────────────────

@pytest.mark.parametrize(
    ("minutos", "esperado"),
    [
        (1, 3000),    # un minuto ya es una fracción iniciada
        (59, 3000),
        (60, 3000),   # exactamente una hora sigue siendo un bloque
        (61, 6000),   # un minuto más y son dos
        (137, 9000),  # 2 h 17 min → tres fracciones
        (180, 9000),
    ],
)
def test_hora_o_fraccion(minutos, esperado):
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla()],
        entrada=entrada,
        salida=entrada + timedelta(minutes=minutos),
        zona=BOGOTA,
    )
    assert c.total == Decimal(esperado)
    assert c.minutos == minutos


def test_fraccion_de_quince_minutos():
    """El mismo modo con otro bloque: no hace falta código nuevo."""
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(bloque_minutos=15, precio_bloque=Decimal(1000))],
        entrada=entrada,
        salida=entrada + timedelta(minutes=31),
        zona=BOGOTA,
    )
    assert c.total == Decimal(3000)  # 3 fracciones de 15


def test_por_minuto():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(modo=ModoCobro.POR_MINUTO, precio_minuto=Decimal(60))],
        entrada=entrada,
        salida=entrada + timedelta(minutes=137),
        zona=BOGOTA,
    )
    assert c.total == Decimal(137 * 60)


def test_primera_hora_completa_y_luego_por_minuto():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[
            regla(
                modo=ModoCobro.PRIMER_BLOQUE_LUEGO_MINUTO,
                precio_bloque=Decimal(3000),
                precio_minuto=Decimal(50),
            )
        ],
        entrada=entrada,
        salida=entrada + timedelta(minutes=137),
        zona=BOGOTA,
    )
    # 3000 de la primera hora + 77 min × 50
    assert c.total == Decimal(3000) + Decimal(77 * 50)


def test_primera_hora_sola_no_cobra_minutos_extra():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[
            regla(
                modo=ModoCobro.PRIMER_BLOQUE_LUEGO_MINUTO,
                precio_bloque=Decimal(3000),
                precio_minuto=Decimal(50),
            )
        ],
        entrada=entrada,
        salida=entrada + timedelta(minutes=45),
        zona=BOGOTA,
    )
    assert c.total == Decimal(3000)


def test_tarifa_plena():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(modo=ModoCobro.PLENA, precio_plena=Decimal(12000))],
        entrada=entrada,
        salida=entrada + timedelta(hours=9),
        zona=BOGOTA,
    )
    assert c.total == Decimal(12000)


def test_por_dia():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(modo=ModoCobro.POR_DIA, precio_dia=Decimal(25000), dia_horas=24)],
        entrada=entrada,
        salida=entrada + timedelta(hours=26),
        zona=BOGOTA,
    )
    assert c.total == Decimal(50000)  # 26 h → dos días iniciados


# ── Escalonado ───────────────────────────────────────────────────────────

def escalonada(**cambios) -> ReglaTarifaria:
    """"$3.000 la primera hora, $2.000 cada hora adicional"."""
    base = {
        "codigo": "carro",
        "modo": ModoCobro.ESCALONADO,
        "escalones": (
            Escalon(0, 60, Decimal(3000), UnidadEscalon.FIJO),
            Escalon(60, None, Decimal(2000), UnidadEscalon.BLOQUE, bloque_minutos=60),
        ),
    }
    return ReglaTarifaria(**{**base, **cambios})


@pytest.mark.parametrize(
    ("minutos", "esperado"),
    [
        (30, 3000),    # dentro del primer escalón
        (60, 3000),
        (61, 5000),    # 3000 + una hora adicional iniciada
        (137, 7000),   # 3000 + 2 horas adicionales (77 min)
        (300, 11000),  # 3000 + 4 horas adicionales
    ],
)
def test_escalonado(minutos, esperado):
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[escalonada()],
        entrada=entrada,
        salida=entrada + timedelta(minutes=minutos),
        zona=BOGOTA,
    )
    assert c.total == Decimal(esperado)


def test_escalonado_con_tope_diario():
    """Diez horas costarían $21.000, pero el tope las deja en $20.000."""
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[escalonada(tope_diario=Decimal(20000))],
        entrada=entrada,
        salida=entrada + timedelta(hours=10),
        zona=BOGOTA,
    )
    assert c.total == Decimal(20000)
    assert c.tope_aplicado


# ── Modificadores ────────────────────────────────────────────────────────

def test_cortesia():
    """Por debajo de la gracia el ticket sale en cero."""
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(gracia_minutos=15)],
        entrada=entrada,
        salida=entrada + timedelta(minutes=12),
        zona=BOGOTA,
    )
    assert c.total == Decimal(0)
    assert c.en_cortesia


def test_pasarse_de_la_gracia_por_un_minuto_ya_cobra():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(gracia_minutos=15)],
        entrada=entrada,
        salida=entrada + timedelta(minutes=16),
        zona=BOGOTA,
    )
    assert c.total == Decimal(3000)
    assert not c.en_cortesia


def test_la_cortesia_no_perdona_los_articulos():
    """El tiempo sale gratis; el casco que se llevó, no."""
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(gracia_minutos=15)],
        entrada=entrada,
        salida=entrada + timedelta(minutes=5),
        zona=BOGOTA,
        items=[ItemCobrado("casco", "Casco", Decimal(1000))],
    )
    assert c.total == Decimal(1000)
    assert c.en_cortesia


def test_cobro_minimo():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[
            regla(modo=ModoCobro.POR_MINUTO, precio_minuto=Decimal(50),
                  cobro_minimo=Decimal(2000))
        ],
        entrada=entrada,
        salida=entrada + timedelta(minutes=10),  # serían 500
        zona=BOGOTA,
    )
    assert c.total == Decimal(2000)
    assert c.minimo_aplicado


def test_el_cobro_minimo_no_se_aplica_en_cortesia():
    """Si no, la gracia no serviría de nada."""
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[
            regla(modo=ModoCobro.POR_MINUTO, precio_minuto=Decimal(50),
                  cobro_minimo=Decimal(2000), gracia_minutos=15)
        ],
        entrada=entrada,
        salida=entrada + timedelta(minutes=10),
        zona=BOGOTA,
    )
    assert c.total == Decimal(0)


@pytest.mark.parametrize(
    ("modo", "esperado"),
    [
        (ModoRedondeo.ARRIBA, 4150),
        (ModoRedondeo.ABAJO, 4100),
        (ModoRedondeo.CERCANO, 4150),
    ],
)
def test_redondeo_a_multiplos_de_cincuenta(modo, esperado):
    """En efectivo no existen las monedas de $27."""
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[
            regla(modo=ModoCobro.POR_MINUTO, precio_minuto=Decimal(51),
                  redondeo_modo=modo, redondeo_paso=50)
        ],
        entrada=entrada,
        salida=entrada + timedelta(minutes=81),  # 4131
        zona=BOGOTA,
    )
    assert c.total == Decimal(esperado)
    assert c.total - c.subtotal - c.impuesto == c.ajuste_redondeo


def test_tope_diario_en_estadia_de_varios_dias():
    """Cada ventana de 24 h desde la entrada tiene su propio tope."""
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(precio_bloque=Decimal(2000), tope_diario=Decimal(20000))],
        entrada=entrada,
        salida=entrada + timedelta(hours=50),
        zona=BOGOTA,
    )
    # 24 h + 24 h topadas a 20000, más 2 bloques sueltos de la tercera ventana
    assert c.total == Decimal(20000 + 20000 + 4000)


# ── Franjas horarias ─────────────────────────────────────────────────────

DIURNA = ReglaTarifaria(
    codigo="carro-dia",
    modo=ModoCobro.POR_BLOQUE,
    precio_bloque=Decimal(3000),
    bloque_minutos=60,
    franja=Franja(desde_hora=time(6, 0), hasta_hora=time(20, 0)),
    prioridad=10,
)
NOCTURNA = ReglaTarifaria(
    codigo="carro-noche",
    modo=ModoCobro.POR_BLOQUE,
    precio_bloque=Decimal(1500),
    bloque_minutos=60,
    franja=Franja(desde_hora=time(20, 0), hasta_hora=time(6, 0)),
    prioridad=10,
)


def test_estadia_dentro_de_una_sola_franja():
    c = cotizar(
        reglas=[DIURNA, NOCTURNA],
        entrada=momento(24, 10),
        salida=momento(24, 13),
        zona=BOGOTA,
    )
    assert c.total == Decimal(9000)
    assert c.regla_aplicada == "carro-dia"


def test_estadia_que_cruza_a_la_tarifa_nocturna():
    """19:00 → 22:00: una hora diurna y dos nocturnas."""
    c = cotizar(
        reglas=[DIURNA, NOCTURNA],
        entrada=momento(24, 19),
        salida=momento(24, 22),
        zona=BOGOTA,
    )
    assert c.total == Decimal(3000 + 3000)
    assert len(c.lineas) == 2


def test_una_fraccion_iniciada_en_el_borde_de_la_franja_se_cobra_completa():
    """19:30 → 21:00. Media hora diurna cuesta una fracción diurna entera."""
    c = cotizar(
        reglas=[DIURNA, NOCTURNA],
        entrada=momento(24, 19, 30),
        salida=momento(24, 21),
        zona=BOGOTA,
    )
    assert c.total == Decimal(3000 + 1500)


def test_estadia_que_cruza_la_medianoche():
    """22:00 → 07:00: ocho horas nocturnas y una diurna."""
    c = cotizar(
        reglas=[DIURNA, NOCTURNA],
        entrada=momento(24, 22),
        salida=momento(25, 7),
        zona=BOGOTA,
    )
    assert c.total == Decimal(8 * 1500 + 3000)


def test_tarifa_de_fin_de_semana():
    """2026-08-29 es sábado."""
    finde = ReglaTarifaria(
        codigo="carro-finde",
        modo=ModoCobro.POR_BLOQUE,
        precio_bloque=Decimal(2000),
        bloque_minutos=60,
        franja=Franja(dias=frozenset({5, 6})),
        prioridad=20,
    )
    base = regla(precio_bloque=Decimal(3000))

    sabado = cotizar(reglas=[base, finde], entrada=momento(29, 10),
                     salida=momento(29, 13), zona=BOGOTA)
    assert sabado.total == Decimal(6000)

    lunes = cotizar(reglas=[base, finde], entrada=momento(24, 10),
                    salida=momento(24, 13), zona=BOGOTA)
    assert lunes.total == Decimal(9000)


def test_los_modificadores_salen_de_la_regla_de_entrada():
    """Aunque la estadía cruce franjas, la gracia es la de la entrada.

    Si no fuera así, bastaría con entrar justo antes de un cambio de franja
    para elegir el modificador más conveniente.
    """
    diurna_con_gracia = ReglaTarifaria(
        codigo="dia", modo=ModoCobro.POR_BLOQUE, precio_bloque=Decimal(3000),
        franja=Franja(desde_hora=time(6, 0), hasta_hora=time(20, 0)),
        gracia_minutos=20,
    )
    nocturna_sin_gracia = ReglaTarifaria(
        codigo="noche", modo=ModoCobro.POR_BLOQUE, precio_bloque=Decimal(1500),
        franja=Franja(desde_hora=time(20, 0), hasta_hora=time(6, 0)),
        gracia_minutos=0,
    )
    c = cotizar(
        reglas=[diurna_con_gracia, nocturna_sin_gracia],
        entrada=momento(24, 19, 50),
        salida=momento(24, 20, 5),  # 15 min, cruza la medianoche de la franja
        zona=BOGOTA,
    )
    assert c.en_cortesia
    assert c.total == Decimal(0)


def test_los_modos_no_segmentables_usan_la_regla_de_la_entrada():
    """El escalonado no se parte por franjas: sus tramos ya varían con el tiempo."""
    esc_dia = ReglaTarifaria(
        codigo="esc-dia", modo=ModoCobro.ESCALONADO,
        escalones=(Escalon(0, 60, Decimal(3000), UnidadEscalon.FIJO),
                   Escalon(60, None, Decimal(2000), UnidadEscalon.BLOQUE)),
        franja=Franja(desde_hora=time(6, 0), hasta_hora=time(20, 0)),
    )
    nocturna = ReglaTarifaria(
        codigo="noche", modo=ModoCobro.POR_BLOQUE, precio_bloque=Decimal(1500),
        franja=Franja(desde_hora=time(20, 0), hasta_hora=time(6, 0)),
    )
    c = cotizar(
        reglas=[esc_dia, nocturna],
        entrada=momento(24, 19),
        salida=momento(24, 22),  # 3 h, cruzaría a nocturna
        zona=BOGOTA,
    )
    # Se cobra entero con el escalonado: 3000 + 2 horas adicionales
    assert c.total == Decimal(7000)
    assert c.regla_aplicada == "esc-dia"


# ── Festivos ─────────────────────────────────────────────────────────────

def test_tarifa_de_festivo():
    """2026-08-25 es martes; se declara festivo para la prueba."""
    festiva = ReglaTarifaria(
        codigo="festivo", modo=ModoCobro.POR_BLOQUE, precio_bloque=Decimal(4000),
        franja=Franja(solo_festivos=True), prioridad=100,
    )
    base = regla(precio_bloque=Decimal(3000))
    festivos = frozenset({momento(25, 10).date()})

    c = cotizar(reglas=[base, festiva], entrada=momento(25, 10),
                salida=momento(25, 12), zona=BOGOTA, festivos=festivos)
    assert c.total == Decimal(8000)

    normal = cotizar(reglas=[base, festiva], entrada=momento(25, 10),
                     salida=momento(25, 12), zona=BOGOTA)
    assert normal.total == Decimal(6000)


# ── Artículos e impuestos ────────────────────────────────────────────────

def test_articulos_adicionales():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla()],
        entrada=entrada,
        salida=entrada + timedelta(minutes=137),
        zona=BOGOTA,
        items=[ItemCobrado("casco", "Casco", Decimal(1000), cantidad=2)],
    )
    assert c.total == Decimal(9000 + 2000)
    assert any("Casco" in linea.concepto for linea in c.lineas)


def test_iva_incluido_es_informativo():
    """El precio mostrado ya lo lleva dentro: el total no cambia."""
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(impuesto_modo=ModoImpuesto.INCLUIDO,
                      impuesto_tasa=Decimal("0.19"))],
        entrada=entrada,
        salida=entrada + timedelta(hours=1),
        zona=BOGOTA,
    )
    assert c.total == Decimal(3000)
    assert c.impuesto > 0
    assert c.subtotal + c.impuesto == Decimal(3000)


def test_iva_agregado_suma_al_total():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(impuesto_modo=ModoImpuesto.AGREGADO,
                      impuesto_tasa=Decimal("0.19"))],
        entrada=entrada,
        salida=entrada + timedelta(hours=1),
        zona=BOGOTA,
    )
    assert c.subtotal == Decimal(3000)
    assert c.impuesto == Decimal(570)
    assert c.total == Decimal(3570)


# ── Casos límite ─────────────────────────────────────────────────────────

def test_salida_antes_de_la_entrada():
    entrada = momento(24, 10)
    with pytest.raises(SalidaAntesDeEntrada):
        cotizar(reglas=[regla()], entrada=entrada,
                salida=entrada - timedelta(minutes=1), zona=BOGOTA)


def test_entrada_y_salida_iguales():
    entrada = momento(24, 10)
    c = cotizar(reglas=[regla()], entrada=entrada, salida=entrada, zona=BOGOTA)
    assert c.minutos == 0
    assert c.total == Decimal(0)


def test_sin_regla_aplicable_es_un_error_explicito():
    solo_finde = ReglaTarifaria(
        codigo="finde", modo=ModoCobro.POR_BLOQUE, precio_bloque=Decimal(2000),
        franja=Franja(dias=frozenset({5, 6})),
    )
    with pytest.raises(LookupError):
        cotizar(reglas=[solo_finde], entrada=momento(24, 10),
                salida=momento(24, 12), zona=BOGOTA)


def test_la_duracion_se_mide_en_tiempo_absoluto_pese_al_cambio_de_hora():
    """Colombia no cambia la hora, pero un cliente en otro país sí.

    Santiago de Chile adelanta el reloj el 2026-09-06 a las 00:00: esa
    noche el reloj de pared salta de 23:59 a 01:00. Una estadía de tres
    horas reales debe cobrarse como tres horas, no como cuatro.
    """
    santiago = ZoneInfo("America/Santiago")
    entrada = datetime(2026, 9, 5, 23, 0, tzinfo=santiago)
    salida = entrada + timedelta(hours=3)

    c = cotizar(reglas=[regla()], entrada=entrada, salida=salida, zona=santiago)
    assert c.minutos == 180
    assert c.total == Decimal(9000)


# ── Casos adversarios ────────────────────────────────────────────────────
# Bordes donde la implementación podría estar mintiendo sin que se note.


def test_bloque_que_no_divide_el_dia_no_se_infla_por_el_corte_de_24h():
    """El corte de 24 h existe para repartir el tope, no para cobrar de más.

    Con bloques de 50 min, partir a las 24 h redondearía hacia arriba dos
    veces. Sin tope no debe haber corte, y el cobro tiene que ser el mismo
    que si se calculara de una sola vez.
    """
    entrada = momento(24, 8)
    salida = entrada + timedelta(hours=25)  # 1500 min
    sin_tope = cotizar(
        reglas=[regla(bloque_minutos=50, precio_bloque=Decimal(1000))],
        entrada=entrada, salida=salida, zona=BOGOTA,
    )
    # 1500 / 50 = 30 bloques exactos, sin fracción artificial en el corte.
    assert sin_tope.total == Decimal(30000)


def test_estadia_de_exactamente_veinticuatro_horas_es_una_sola_ventana():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(precio_bloque=Decimal(1000), tope_diario=Decimal(50000))],
        entrada=entrada, salida=entrada + timedelta(hours=24), zona=BOGOTA,
    )
    assert c.total == Decimal(24000)  # 24 bloques, por debajo del tope
    assert not c.tope_aplicado


def test_un_minuto_mas_de_veinticuatro_horas_abre_la_segunda_ventana():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(precio_bloque=Decimal(1000), tope_diario=Decimal(10000))],
        entrada=entrada, salida=entrada + timedelta(hours=24, minutes=1), zona=BOGOTA,
    )
    # Primera ventana topada en 10000 + un bloque iniciado en la segunda.
    assert c.total == Decimal(11000)
    assert c.tope_aplicado


def test_tope_menor_que_un_solo_bloque():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(precio_bloque=Decimal(5000), tope_diario=Decimal(3000))],
        entrada=entrada, salida=entrada + timedelta(minutes=30), zona=BOGOTA,
    )
    assert c.total == Decimal(3000)
    assert c.tope_aplicado


def test_escalon_por_minuto():
    """Un escalón puede cobrarse al minuto, no solo por bloques."""
    entrada = momento(24, 8)
    r = ReglaTarifaria(
        codigo="mixta",
        modo=ModoCobro.ESCALONADO,
        escalones=(
            Escalon(0, 30, Decimal(2000), UnidadEscalon.FIJO),
            Escalon(30, None, Decimal(100), UnidadEscalon.MINUTO),
        ),
    )
    c = cotizar(reglas=[r], entrada=entrada,
                salida=entrada + timedelta(minutes=45), zona=BOGOTA)
    assert c.total == Decimal(2000) + Decimal(15 * 100)


def test_dos_reglas_con_la_misma_prioridad_resuelven_igual_sin_importar_el_orden():
    """El resultado no puede depender de cómo vengan ordenadas de la base."""
    a = ReglaTarifaria(
        codigo="a", modo=ModoCobro.POR_BLOQUE, precio_bloque=Decimal(3000),
        franja=Franja(desde_hora=time(6, 0), hasta_hora=time(20, 0)), prioridad=5,
    )
    b = ReglaTarifaria(
        codigo="b", modo=ModoCobro.POR_BLOQUE, precio_bloque=Decimal(9000),
        franja=Franja(desde_hora=time(8, 0), hasta_hora=time(12, 0)), prioridad=5,
    )
    uno = cotizar(reglas=[a, b], entrada=momento(24, 9), salida=momento(24, 10), zona=BOGOTA)
    otro = cotizar(reglas=[b, a], entrada=momento(24, 9), salida=momento(24, 10), zona=BOGOTA)
    assert uno.regla_aplicada == otro.regla_aplicada
    assert uno.total == otro.total


def test_el_redondeo_hacia_abajo_no_deja_el_total_bajo_el_cobro_minimo():
    """Si el mínimo son $2.000, cobrar $1.950 lo incumple."""
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[
            regla(modo=ModoCobro.POR_MINUTO, precio_minuto=Decimal(1),
                  cobro_minimo=Decimal(1980),
                  redondeo_modo=ModoRedondeo.ABAJO, redondeo_paso=100)
        ],
        entrada=entrada, salida=entrada + timedelta(minutes=10), zona=BOGOTA,
    )
    assert c.total >= Decimal(1980), f"el redondeo se comió el mínimo: {c.total}"


def test_las_lineas_suman_el_total():
    """El desglose que ve el cliente tiene que cuadrar con lo que paga."""
    entrada = momento(24, 19)
    c = cotizar(
        reglas=[DIURNA, NOCTURNA],
        entrada=entrada, salida=momento(25, 7), zona=BOGOTA,
        items=[ItemCobrado("casco", "Casco", Decimal(1000))],
    )
    suma = sum((linea.monto for linea in c.lineas), Decimal(0))
    assert suma == c.total


def test_las_lineas_suman_el_total_tambien_con_tope_y_minimo():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(precio_bloque=Decimal(2000), tope_diario=Decimal(20000),
                      redondeo_paso=50)],
        entrada=entrada, salida=entrada + timedelta(hours=50), zona=BOGOTA,
        items=[ItemCobrado("lavada", "Lavada", Decimal(15000))],
    )
    suma = sum((linea.monto for linea in c.lineas), Decimal(0))
    assert suma == c.total


def test_la_mensualidad_avisa_que_todavia_no_existe():
    """Mejor un error explícito que cobrar cero sin que nadie se entere."""
    entrada = momento(24, 8)
    with pytest.raises(NotImplementedError):
        cotizar(
            reglas=[regla(modo=ModoCobro.MENSUALIDAD)],
            entrada=entrada, salida=entrada + timedelta(hours=2), zona=BOGOTA,
        )


def test_los_segundos_sueltos_cuentan_como_minuto_iniciado():
    entrada = momento(24, 8)
    c = cotizar(
        reglas=[regla(modo=ModoCobro.POR_MINUTO, precio_minuto=Decimal(100))],
        entrada=entrada, salida=entrada + timedelta(minutes=10, seconds=1), zona=BOGOTA,
    )
    assert c.minutos == 11
    assert c.total == Decimal(1100)
