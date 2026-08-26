"""Motor de tarifas.

Función pura: entra el snapshot de las reglas y dos instantes, sale el
desglose. Sin base de datos, sin FastAPI, sin reloj propio —la hora de
salida siempre llega como parámetro, para que el resultado sea
reproducible y auditable años después.

## Orden de las operaciones

1. Duración en tiempo **absoluto** (no en horas de reloj: el cambio de
   horario de verano no debe regalar ni cobrar una hora de más).
2. Cortesía: por debajo de la gracia, el estacionamiento sale en cero.
3. Se parte la estadía en tramos y se cobra cada uno con su regla.
4. Tope por cada ventana de 24 h desde la entrada.
5. Cobro mínimo.
6. Artículos y servicios.
7. Impuesto.
8. Redondeo del total.

## Dos decisiones que conviene tener presentes

**Los modificadores salen siempre de la regla vigente a la entrada**
—gracia, mínimo, tope, redondeo, impuesto— aunque la estadía cruce
franjas. Si dependieran del tramo, bastaría con entrar justo antes de un
cambio de franja para elegir el más conveniente.

**Solo se segmentan los modos por unidad de tiempo** (`POR_MINUTO` y
`POR_BLOQUE`). Los demás se refieren a la posición dentro de la estadía
—la primera hora, los escalones, la tarifa plena— y partirlos daría
resultados que nadie sabría explicarle a un cliente. Esos usan la regla
de la entrada para toda la estadía.
"""

import math
from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

from app.domain.pricing.modelos import (
    Cotizacion,
    Franja,
    ItemCobrado,
    LineaCargo,
    ModoCobro,
    ModoImpuesto,
    ModoRedondeo,
    ReglaTarifaria,
    UnidadEscalon,
)
from app.domain.pricing.redondeo import a_centavos, redondear

MINUTOS_POR_DIA = 24 * 60


class SalidaAntesDeEntrada(ValueError):
    def __init__(self) -> None:
        super().__init__("La salida no puede ser anterior a la entrada")


class SinReglaAplicable(LookupError):
    def __init__(self, momento: datetime) -> None:
        super().__init__(f"Ninguna tarifa aplica a las {momento:%Y-%m-%d %H:%M}")


class ModoNoDisponible(NotImplementedError):
    pass


# ── Selección de la regla ────────────────────────────────────────────────

def _amplitud(franja: Franja | None) -> int:
    """Cuántos minutos de la semana cubre la franja. Menos es más específico."""
    if franja is None:
        return 10**9  # la regla base es lo más general que hay

    if franja.todo_el_dia:
        minutos = MINUTOS_POR_DIA
    elif franja.cruza_medianoche:
        desde = franja.desde_hora.hour * 60 + franja.desde_hora.minute
        hasta = franja.hasta_hora.hour * 60 + franja.hasta_hora.minute
        minutos = (MINUTOS_POR_DIA - desde) + hasta
    else:
        desde = franja.desde_hora.hour * 60 + franja.desde_hora.minute
        hasta = franja.hasta_hora.hour * 60 + franja.hasta_hora.minute
        minutos = hasta - desde

    dias = 1 if franja.solo_festivos else max(1, len(franja.dias))
    return minutos * dias


def _regla_vigente(
    reglas: Sequence[ReglaTarifaria],
    momento_local: datetime,
    festivos: frozenset[date],
) -> ReglaTarifaria:
    """La regla que aplica en ese instante.

    El desempate es total y no depende del orden en que lleguen las reglas.
    Eso importa más de lo que parece: sin un criterio completo, el mismo
    ticket podría cobrarse distinto según cómo la base devolviera las filas.

    1. Mayor prioridad.
    2. Franja más específica —la que cubre menos tiempo de la semana—,
       de modo que "8 a 12" le gana a "6 a 20" y ambas a la regla base.
    3. Código alfabético, para que ni un empate perfecto sea ambiguo.
    """
    candidatas = [
        r for r in reglas
        if r.franja is None or r.franja.cubre(momento_local, festivos)
    ]
    if not candidatas:
        raise SinReglaAplicable(momento_local)
    return min(candidatas, key=lambda r: (-r.prioridad, _amplitud(r.franja), r.codigo))


# ── Partición de la estadía ──────────────────────────────────────────────

def _fronteras(
    entrada: datetime,
    salida: datetime,
    zona: ZoneInfo,
    reglas: Sequence[ReglaTarifaria],
    partir_por_dia: bool,
) -> list[datetime]:
    """Instantes donde puede cambiar la tarifa."""
    puntos = {entrada, salida}

    # Cortes de cada 24 h desde la entrada, solo si hay tope diario que
    # repartir. Sin tope no se parte: si el bloque no divide exacto el día,
    # un corte artificial cobraría una fracción de más.
    if partir_por_dia:
        corte = entrada + timedelta(days=1)
        while corte < salida:
            puntos.add(corte)
            corte += timedelta(days=1)

    # Bordes de las franjas, en hora local de la sede.
    dia = entrada.astimezone(zona).date()
    ultimo = salida.astimezone(zona).date()
    while dia <= ultimo:
        for r in reglas:
            if r.franja is None:
                continue
            for hora in (r.franja.desde_hora, r.franja.hasta_hora):
                borde = datetime.combine(dia, hora, tzinfo=zona)
                if entrada < borde < salida:
                    puntos.add(borde)
        dia += timedelta(days=1)

    return sorted(puntos)


# ── Cobro de un tramo ────────────────────────────────────────────────────

def _minutos(desde: datetime, hasta: datetime) -> int:
    """Minutos absolutos, redondeando hacia arriba la fracción de minuto."""
    return math.ceil((hasta - desde).total_seconds() / 60)


def _cobrar_escalones(regla: ReglaTarifaria, minutos: int) -> Decimal:
    total = Decimal(0)
    for escalon in sorted(regla.escalones, key=lambda e: e.desde_minuto):
        if minutos <= escalon.desde_minuto:
            break
        fin = min(minutos, escalon.hasta_minuto or minutos)
        tramo = fin - escalon.desde_minuto
        if tramo <= 0:
            continue

        if escalon.unidad is UnidadEscalon.FIJO:
            total += escalon.precio
        elif escalon.unidad is UnidadEscalon.MINUTO:
            total += escalon.precio * tramo
        else:
            total += escalon.precio * math.ceil(tramo / escalon.bloque_minutos)
    return total


def _cobrar_tramo(regla: ReglaTarifaria, minutos: int) -> tuple[Decimal, str]:
    """Devuelve (monto, detalle legible) de un tramo de `minutos`."""
    if minutos <= 0:
        return Decimal(0), "sin tiempo"

    match regla.modo:
        case ModoCobro.POR_MINUTO:
            return regla.precio_minuto * minutos, f"{minutos} min"

        case ModoCobro.POR_BLOQUE:
            bloques = math.ceil(minutos / regla.bloque_minutos)
            return (
                regla.precio_bloque * bloques,
                f"{bloques} × {regla.bloque_minutos} min",
            )

        case ModoCobro.PRIMER_BLOQUE_LUEGO_MINUTO:
            extra = max(0, minutos - regla.bloque_minutos)
            monto = regla.precio_bloque + regla.precio_minuto * extra
            detalle = f"primer bloque de {regla.bloque_minutos} min"
            if extra:
                detalle += f" + {extra} min"
            return monto, detalle

        case ModoCobro.ESCALONADO:
            return _cobrar_escalones(regla, minutos), f"{minutos} min por escalones"

        case ModoCobro.PLENA:
            return regla.precio_plena, "tarifa plena"

        case ModoCobro.POR_DIA:
            minutos_dia = regla.dia_horas * 60
            dias = math.ceil(minutos / minutos_dia)
            return regla.precio_dia * dias, f"{dias} × {regla.dia_horas} h"

        case ModoCobro.MENSUALIDAD:
            raise ModoNoDisponible(
                "Las mensualidades llegan en la fase 5 (ver docs/DECISIONES.md, D2)"
            )

    raise ModoNoDisponible(f"Modo de cobro desconocido: {regla.modo}")


# ── Motor ────────────────────────────────────────────────────────────────

def cotizar(
    *,
    reglas: Sequence[ReglaTarifaria],
    entrada: datetime,
    salida: datetime,
    zona: ZoneInfo,
    items: Sequence[ItemCobrado] = (),
    festivos: frozenset[date] = frozenset(),
) -> Cotizacion:
    """Calcula lo que hay que cobrar por una estadía."""
    if entrada.tzinfo is None or salida.tzinfo is None:
        raise ValueError("Entrada y salida deben llevar zona horaria")
    if salida < entrada:
        raise SalidaAntesDeEntrada()
    if not reglas:
        raise SinReglaAplicable(entrada)

    minutos_totales = _minutos(entrada, salida)
    base = _regla_vigente(reglas, entrada.astimezone(zona), festivos)

    lineas: list[LineaCargo] = []
    en_cortesia = minutos_totales <= base.gracia_minutos
    tope_aplicado = False
    minimo_aplicado = False
    cargo = Decimal(0)

    if en_cortesia and minutos_totales > 0:
        lineas.append(
            LineaCargo("Cortesía", Decimal(0), detalle=f"{minutos_totales} min sin cobro")
        )
    elif minutos_totales > 0:
        cargo, lineas_tiempo, tope_aplicado = _cobrar_estadia(
            reglas, base, entrada, salida, zona, festivos
        )
        lineas.extend(lineas_tiempo)

        if base.cobro_minimo is not None and cargo < base.cobro_minimo:
            lineas.append(
                LineaCargo(
                    "Ajuste por cobro mínimo",
                    base.cobro_minimo - cargo,
                    detalle=f"mínimo de {base.cobro_minimo}",
                )
            )
            cargo = base.cobro_minimo
            minimo_aplicado = True

    for item in items:
        concepto = item.nombre if item.cantidad == 1 else f"{item.nombre} × {item.cantidad}"
        lineas.append(LineaCargo(concepto, item.total, cantidad=Decimal(item.cantidad)))
        cargo += item.total

    # Impuesto. "Incluido" es lo normal en Colombia: el precio en la valla
    # ya lo lleva dentro, así que aquí solo se desglosa.
    if base.impuesto_tasa > 0 and base.impuesto_modo is ModoImpuesto.INCLUIDO:
        subtotal = a_centavos(cargo / (Decimal(1) + base.impuesto_tasa))
        impuesto = a_centavos(cargo - subtotal)
        antes_de_redondear = subtotal + impuesto
    elif base.impuesto_tasa > 0:
        subtotal = a_centavos(cargo)
        impuesto = a_centavos(cargo * base.impuesto_tasa)
        antes_de_redondear = subtotal + impuesto
    else:
        subtotal = a_centavos(cargo)
        impuesto = Decimal("0.00")
        antes_de_redondear = subtotal

    total = redondear(antes_de_redondear, base.redondeo_modo, base.redondeo_paso)

    # El cobro mínimo es una promesa del parqueadero: redondear hacia abajo
    # por debajo de él la incumpliría. Cuando el mínimo entró en juego, el
    # redondeo va hacia arriba aunque la regla diga otra cosa.
    if minimo_aplicado and total < antes_de_redondear:
        total = redondear(antes_de_redondear, ModoRedondeo.ARRIBA, base.redondeo_paso)

    ajuste = a_centavos(total - antes_de_redondear)
    if ajuste:
        lineas.append(LineaCargo("Redondeo", ajuste))

    return Cotizacion(
        minutos=minutos_totales,
        minutos_facturables=0 if en_cortesia else minutos_totales,
        lineas=tuple(lineas),
        subtotal=subtotal,
        impuesto=impuesto,
        ajuste_redondeo=ajuste,
        total=total,
        regla_aplicada=base.codigo,
        en_cortesia=en_cortesia,
        tope_aplicado=tope_aplicado,
        minimo_aplicado=minimo_aplicado,
    )


def _cobrar_estadia(
    reglas: Sequence[ReglaTarifaria],
    base: ReglaTarifaria,
    entrada: datetime,
    salida: datetime,
    zona: ZoneInfo,
    festivos: frozenset[date],
) -> tuple[Decimal, list[LineaCargo], bool]:
    """Cobra el tiempo, ya sea de una vez o partido en tramos."""
    hay_tope = base.tope_diario is not None

    # Los modos que se refieren a la posición dentro de la estadía no se
    # parten: se cobran enteros con la regla de la entrada.
    if not base.segmentable:
        minutos = _minutos(entrada, salida)
        monto, detalle = _cobrar_tramo(base, minutos)
        tope_aplicado = False
        if hay_tope:
            ventanas = max(1, math.ceil(minutos / MINUTOS_POR_DIA))
            techo = base.tope_diario * ventanas
            if monto > techo:
                monto, tope_aplicado = techo, True
        return monto, [LineaCargo(_titulo(base), monto, detalle=detalle)], tope_aplicado

    fronteras = _fronteras(entrada, salida, zona, reglas, partir_por_dia=hay_tope)

    # Se agrupa por ventana de 24 h desde la entrada: cada una tiene su tope.
    por_ventana: dict[int, list[LineaCargo]] = {}
    for desde, hasta in zip(fronteras, fronteras[1:], strict=False):
        minutos = _minutos(desde, hasta)
        if minutos <= 0:
            continue
        regla = _regla_vigente(reglas, desde.astimezone(zona), festivos)
        monto, detalle = _cobrar_tramo(regla, minutos)
        ventana = int((desde - entrada).total_seconds() // 60) // MINUTOS_POR_DIA
        por_ventana.setdefault(ventana, []).append(
            LineaCargo(_titulo(regla), monto, detalle=detalle)
        )

    total = Decimal(0)
    lineas: list[LineaCargo] = []
    tope_aplicado = False
    for ventana in sorted(por_ventana):
        del_dia = por_ventana[ventana]
        suma = sum((linea.monto for linea in del_dia), Decimal(0))
        lineas.extend(del_dia)

        if hay_tope and suma > base.tope_diario:
            lineas.append(
                LineaCargo(
                    "Tope diario",
                    base.tope_diario - suma,
                    detalle=f"máximo {base.tope_diario} por cada 24 h",
                )
            )
            suma = base.tope_diario
            tope_aplicado = True
        total += suma

    return total, lineas, tope_aplicado


def _titulo(regla: ReglaTarifaria) -> str:
    titulos = {
        ModoCobro.POR_MINUTO: "Tiempo por minuto",
        ModoCobro.POR_BLOQUE: "Tiempo por fracción",
        ModoCobro.PRIMER_BLOQUE_LUEGO_MINUTO: "Primer bloque y minutos",
        ModoCobro.ESCALONADO: "Tiempo por escalones",
        ModoCobro.PLENA: "Tarifa plena",
        ModoCobro.POR_DIA: "Tiempo por días",
        ModoCobro.MENSUALIDAD: "Mensualidad",
    }
    return titulos.get(regla.modo, "Tiempo")
