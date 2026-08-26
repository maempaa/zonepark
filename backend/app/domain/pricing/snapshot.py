"""Puente entre las tablas de tarifas y el motor.

Hace dos cosas:

1. Convierte filas de `rate_rules` en `ReglaTarifaria`, que es lo único
   que el motor entiende.
2. Serializa y reconstruye esas reglas en JSON.

La segunda es la importante. Al abrir un ticket se guarda el JSON de las
reglas que le aplican en `tickets.rate_snapshot`. A partir de ahí el
ticket ya no depende de la tabla: si mañana suben la tarifa, o alguien
archiva el plan, ese ticket se sigue cotizando con lo que se le prometió
al cliente al entrar. Y un recálculo dos años después da lo mismo.

Por eso la ida y vuelta tiene que ser exacta. Los `Decimal` viajan como
texto: pasar por float perdería céntimos.
"""

from collections.abc import Iterable, Sequence
from datetime import time
from decimal import Decimal
from typing import Any

from app.domain.pricing.modelos import (
    Escalon,
    Franja,
    ModoCobro,
    ModoImpuesto,
    ModoRedondeo,
    ReglaTarifaria,
    UnidadEscalon,
)

VERSION_SNAPSHOT = 1


# ── Desde la base de datos ───────────────────────────────────────────────

def regla_desde_orm(fila: Any) -> ReglaTarifaria:
    """Convierte una fila de `rate_rules` en una regla del motor."""
    franja = None
    if fila.tiene_franja:
        franja = Franja(
            dias=frozenset(fila.franja_dias or range(7)),
            desde_hora=fila.franja_desde or time(0, 0),
            hasta_hora=fila.franja_hasta or time(0, 0),
            incluye_festivos=fila.franja_incluye_festivos,
            solo_festivos=fila.franja_solo_festivos,
        )

    escalones = tuple(
        Escalon(
            desde_minuto=e.desde_minuto,
            hasta_minuto=e.hasta_minuto,
            precio=e.precio,
            unidad=UnidadEscalon(e.unidad),
            bloque_minutos=e.bloque_minutos,
        )
        for e in sorted(fila.escalones, key=lambda e: e.desde_minuto)
    )

    return ReglaTarifaria(
        codigo=fila.codigo,
        modo=ModoCobro(fila.modo),
        precio_minuto=fila.precio_minuto,
        precio_bloque=fila.precio_bloque,
        precio_plena=fila.precio_plena,
        precio_dia=fila.precio_dia,
        bloque_minutos=fila.bloque_minutos,
        dia_horas=fila.dia_horas,
        escalones=escalones,
        gracia_minutos=fila.gracia_minutos,
        cobro_minimo=fila.cobro_minimo,
        tope_diario=fila.tope_diario,
        tarifa_ticket_perdido=fila.tarifa_ticket_perdido,
        redondeo_modo=ModoRedondeo(fila.redondeo_modo),
        redondeo_paso=fila.redondeo_paso,
        impuesto_modo=ModoImpuesto(fila.impuesto_modo),
        impuesto_tasa=fila.impuesto_tasa,
        franja=franja,
        prioridad=fila.prioridad,
    )


def reglas_de(filas: Iterable[Any]) -> list[ReglaTarifaria]:
    return [regla_desde_orm(f) for f in filas]


# ── Serialización ────────────────────────────────────────────────────────

def _d(valor: Decimal | None) -> str | None:
    return None if valor is None else str(valor)


def _t(valor: time) -> str:
    return valor.strftime("%H:%M:%S")


def serializar(regla: ReglaTarifaria) -> dict[str, Any]:
    datos: dict[str, Any] = {
        "codigo": regla.codigo,
        "modo": regla.modo.value,
        "precio_minuto": _d(regla.precio_minuto),
        "precio_bloque": _d(regla.precio_bloque),
        "precio_plena": _d(regla.precio_plena),
        "precio_dia": _d(regla.precio_dia),
        "bloque_minutos": regla.bloque_minutos,
        "dia_horas": regla.dia_horas,
        "gracia_minutos": regla.gracia_minutos,
        "cobro_minimo": _d(regla.cobro_minimo),
        "tope_diario": _d(regla.tope_diario),
        "tarifa_ticket_perdido": _d(regla.tarifa_ticket_perdido),
        "redondeo_modo": regla.redondeo_modo.value,
        "redondeo_paso": regla.redondeo_paso,
        "impuesto_modo": regla.impuesto_modo.value,
        "impuesto_tasa": _d(regla.impuesto_tasa),
        "prioridad": regla.prioridad,
        "escalones": [
            {
                "desde_minuto": e.desde_minuto,
                "hasta_minuto": e.hasta_minuto,
                "precio": _d(e.precio),
                "unidad": e.unidad.value,
                "bloque_minutos": e.bloque_minutos,
            }
            for e in regla.escalones
        ],
        "franja": None,
    }

    if regla.franja is not None:
        datos["franja"] = {
            "dias": sorted(regla.franja.dias),
            "desde_hora": _t(regla.franja.desde_hora),
            "hasta_hora": _t(regla.franja.hasta_hora),
            "incluye_festivos": regla.franja.incluye_festivos,
            "solo_festivos": regla.franja.solo_festivos,
        }
    return datos


def deserializar(datos: dict[str, Any]) -> ReglaTarifaria:
    franja = None
    if datos.get("franja"):
        f = datos["franja"]
        franja = Franja(
            dias=frozenset(f["dias"]),
            desde_hora=time.fromisoformat(f["desde_hora"]),
            hasta_hora=time.fromisoformat(f["hasta_hora"]),
            incluye_festivos=f["incluye_festivos"],
            solo_festivos=f["solo_festivos"],
        )

    return ReglaTarifaria(
        codigo=datos["codigo"],
        modo=ModoCobro(datos["modo"]),
        precio_minuto=Decimal(datos["precio_minuto"]),
        precio_bloque=Decimal(datos["precio_bloque"]),
        precio_plena=Decimal(datos["precio_plena"]),
        precio_dia=Decimal(datos["precio_dia"]),
        bloque_minutos=datos["bloque_minutos"],
        dia_horas=datos["dia_horas"],
        escalones=tuple(
            Escalon(
                desde_minuto=e["desde_minuto"],
                hasta_minuto=e["hasta_minuto"],
                precio=Decimal(e["precio"]),
                unidad=UnidadEscalon(e["unidad"]),
                bloque_minutos=e["bloque_minutos"],
            )
            for e in datos["escalones"]
        ),
        gracia_minutos=datos["gracia_minutos"],
        cobro_minimo=None if datos["cobro_minimo"] is None else Decimal(datos["cobro_minimo"]),
        tope_diario=None if datos["tope_diario"] is None else Decimal(datos["tope_diario"]),
        tarifa_ticket_perdido=(
            None if datos["tarifa_ticket_perdido"] is None
            else Decimal(datos["tarifa_ticket_perdido"])
        ),
        redondeo_modo=ModoRedondeo(datos["redondeo_modo"]),
        redondeo_paso=datos["redondeo_paso"],
        impuesto_modo=ModoImpuesto(datos["impuesto_modo"]),
        impuesto_tasa=Decimal(datos["impuesto_tasa"]),
        franja=franja,
        prioridad=datos["prioridad"],
    )


def congelar(reglas: Sequence[ReglaTarifaria], *, plan_codigo: str, plan_version: int) -> dict:
    """El JSON que se guarda en el ticket al abrirlo."""
    return {
        "version_snapshot": VERSION_SNAPSHOT,
        "plan_codigo": plan_codigo,
        "plan_version": plan_version,
        "reglas": [serializar(r) for r in reglas],
    }


def descongelar(snapshot: dict) -> list[ReglaTarifaria]:
    version = snapshot.get("version_snapshot")
    if version != VERSION_SNAPSHOT:
        raise ValueError(
            f"Snapshot de tarifas versión {version}; esta build entiende "
            f"la {VERSION_SNAPSHOT}. Hace falta una migración del formato."
        )
    return [deserializar(r) for r in snapshot["reglas"]]
