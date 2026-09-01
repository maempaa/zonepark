"""Tipos del motor de tarifas.

Son dataclasses puras, sin SQLAlchemy ni FastAPI. Dos razones:

1. El motor se prueba sin base de datos ni servidor.
2. Una `ReglaTarifaria` se serializa a JSON tal cual y es exactamente lo
   que se congela en `tickets.rate_snapshot` al abrir el ticket. Si mañana
   suben la tarifa, el ticket de ayer se recalcula con la de ayer.

Todo el dinero es `Decimal`. Nunca float: un céntimo perdido por
redondeo binario es plata mal cobrada, y se acumula.
"""

import enum
from dataclasses import dataclass, field
from datetime import date, datetime, time
from decimal import Decimal


class ModoCobro(enum.StrEnum):
    """Cómo se convierte el tiempo en dinero."""

    POR_MINUTO = "por_minuto"
    POR_BLOQUE = "por_bloque"
    PRIMER_BLOQUE_LUEGO_MINUTO = "primer_bloque_luego_minuto"
    ESCALONADO = "escalonado"
    PLENA = "plena"
    POR_DIA = "por_dia"
    MENSUALIDAD = "mensualidad"


class UnidadEscalon(enum.StrEnum):
    FIJO = "fijo"
    BLOQUE = "bloque"
    MINUTO = "minuto"


class ModoRedondeo(enum.StrEnum):
    ARRIBA = "arriba"
    ABAJO = "abajo"
    CERCANO = "cercano"


class ModoImpuesto(enum.StrEnum):
    INCLUIDO = "incluido"
    AGREGADO = "agregado"


@dataclass(frozen=True, slots=True)
class Escalon:
    """Un tramo de la tarifa escalonada, medido desde la entrada.

    Ejemplo real — "$3.000 la primera hora, $2.000 cada hora adicional":
        Escalon(0, 60, 3000, FIJO)
        Escalon(60, None, 2000, BLOQUE, bloque_minutos=60)
    """

    desde_minuto: int
    hasta_minuto: int | None  # None = sin límite
    precio: Decimal
    unidad: UnidadEscalon = UnidadEscalon.BLOQUE
    bloque_minutos: int = 60

    def __post_init__(self) -> None:
        if self.hasta_minuto is not None and self.hasta_minuto <= self.desde_minuto:
            raise ValueError(
                f"Escalón inválido: hasta_minuto ({self.hasta_minuto}) debe ser mayor "
                f"que desde_minuto ({self.desde_minuto})"
            )
        if self.unidad is UnidadEscalon.BLOQUE and self.bloque_minutos <= 0:
            raise ValueError("Un escalón por bloque necesita bloque_minutos > 0")


@dataclass(frozen=True, slots=True)
class Franja:
    """Cuándo aplica una regla: días de la semana y rango horario.

    `dias` usa la convención de Python: 0 = lunes … 6 = domingo.

    Un rango que termina antes de empezar (20:00 → 06:00) se entiende como
    nocturno y cruza la medianoche.
    """

    dias: frozenset[int] = field(default_factory=lambda: frozenset(range(7)))
    desde_hora: time = time(0, 0)
    hasta_hora: time = time(0, 0)  # igual a desde_hora = todo el día
    incluye_festivos: bool = True
    solo_festivos: bool = False

    @property
    def cruza_medianoche(self) -> bool:
        return self.hasta_hora < self.desde_hora

    @property
    def todo_el_dia(self) -> bool:
        return self.desde_hora == self.hasta_hora

    def cubre(self, momento_local: datetime, festivos: frozenset[date]) -> bool:
        """¿Esta franja aplica en ese instante (hora local de la sede)?"""
        es_festivo = momento_local.date() in festivos

        if self.solo_festivos and not es_festivo:
            return False
        if es_festivo and not self.incluye_festivos and not self.solo_festivos:
            return False

        # En festivo, una franja de festivos ignora el día de la semana.
        ignora_el_dia = es_festivo and self.solo_festivos
        if not ignora_el_dia and momento_local.weekday() not in self.dias:
            return False

        if self.todo_el_dia:
            return True

        hora = momento_local.time()
        if self.cruza_medianoche:
            return hora >= self.desde_hora or hora < self.hasta_hora
        return self.desde_hora <= hora < self.hasta_hora


@dataclass(frozen=True, slots=True)
class ReglaTarifaria:
    """Todo lo que hace falta para cobrar un tipo de vehículo.

    Los modificadores (gracia, mínimo, tope, redondeo, impuesto) se toman
    siempre de la regla vigente **a la entrada**, aunque la estadía cruce
    varias franjas. Si no, un vehículo podría esquivar el cobro mínimo
    entrando justo antes de un cambio de franja.
    """

    codigo: str
    modo: ModoCobro
    # Cómo se le llama a esta opción de cara a quien cobra.
    nombre: str | None = None

    # Precios. Cada modo usa los que le corresponden.
    precio_minuto: Decimal = Decimal(0)
    precio_bloque: Decimal = Decimal(0)
    precio_plena: Decimal = Decimal(0)
    precio_dia: Decimal = Decimal(0)

    bloque_minutos: int = 60
    dia_horas: int = 24
    escalones: tuple[Escalon, ...] = ()

    # Modificadores
    gracia_minutos: int = 0
    cobro_minimo: Decimal | None = None
    tope_diario: Decimal | None = None
    tarifa_ticket_perdido: Decimal | None = None

    redondeo_modo: ModoRedondeo = ModoRedondeo.CERCANO
    redondeo_paso: int = 0  # 0 = sin redondeo

    impuesto_modo: ModoImpuesto = ModoImpuesto.INCLUIDO
    impuesto_tasa: Decimal = Decimal(0)  # 0.19 para IVA del 19 %

    # Cuándo aplica. None = siempre (regla base del plan).
    franja: Franja | None = None
    prioridad: int = 0

    def __post_init__(self) -> None:
        if self.bloque_minutos <= 0:
            raise ValueError("bloque_minutos debe ser mayor que cero")
        if self.dia_horas <= 0:
            raise ValueError("dia_horas debe ser mayor que cero")
        if self.modo is ModoCobro.ESCALONADO and not self.escalones:
            raise ValueError("El modo escalonado necesita al menos un escalón")
        if self.redondeo_paso < 0:
            raise ValueError("redondeo_paso no puede ser negativo")

    @property
    def segmentable(self) -> bool:
        """¿Puede partirse la estadía y cobrar cada tramo con su regla?

        Solo los modos que cobran por unidad de tiempo, porque cada minuto
        vale lo mismo con independencia de cuándo empezó la estadía.

        Los demás se refieren a la *posición* dentro de la estadía —la
        primera hora, los escalones, el precio único, la mensualidad— y
        partirlos por franjas daría resultados que nadie sabría explicarle a
        un cliente. Esos usan la regla vigente a la entrada para todo.
        """
        return self.modo in {ModoCobro.POR_MINUTO, ModoCobro.POR_BLOQUE}


@dataclass(frozen=True, slots=True)
class ItemCobrado:
    """Un artículo o servicio añadido al ticket: casco, lavada, ticket perdido."""

    codigo: str
    nombre: str
    precio_unitario: Decimal
    cantidad: int = 1

    @property
    def total(self) -> Decimal:
        return self.precio_unitario * self.cantidad


@dataclass(frozen=True, slots=True)
class LineaCargo:
    concepto: str
    monto: Decimal
    cantidad: Decimal | None = None
    detalle: str | None = None


@dataclass(frozen=True, slots=True)
class Cotizacion:
    """Lo que devuelve el motor. Es lo que ve el operario y lo que se guarda."""

    minutos: int
    minutos_facturables: int
    lineas: tuple[LineaCargo, ...]
    subtotal: Decimal
    impuesto: Decimal
    ajuste_redondeo: Decimal
    total: Decimal
    regla_aplicada: str
    en_cortesia: bool = False
    tope_aplicado: bool = False
    minimo_aplicado: bool = False
