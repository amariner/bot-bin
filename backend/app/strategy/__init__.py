"""Registro de estrategias disponibles para el bot en vivo.

Una "estrategia" aquí es una clase + sus parámetros validados. Los presets con
parámetros concretos salen de scripts/experiment.py + scripts/holdout.py; no
inventar valores a mano sin pasarlos por esa validación.
"""
from typing import Dict, Tuple, Type

from .base import Strategy
from .meanrev import MeanReversionRSI
from .momentum import MomentumBreakout

# nombre -> (clase, kwargs, descripción)
PRESETS: Dict[str, Tuple[Type[Strategy], dict, str]] = {
    "momentum_4h": (
        MomentumBreakout,
        {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0, "trail_atr": 3.0,
         "max_bars": 0},
        "GANADORA. Rotura selectiva (volumen 4x) con stop dinámico, en velas de "
        "4h. Positiva en las 4 pruebas de validación (periodos y monedas "
        "distintos). Pensada para BOT_TIMEFRAME=4h.",
    ),
    "momentum_4h_ema200": (
        MomentumBreakout,
        {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0, "trail_atr": 3.0,
         "max_bars": 0, "trend_ema": 200},
        "REFUTADA en el test decisivo (periodo virgen abr-dic 25: pierde contra "
        "momentum_4h en los 3 grupos de monedas). Se conserva solo como "
        "referencia del proceso; no usar.",
    ),
    "momentum_trail": (
        MomentumBreakout,
        {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0, "trail_atr": 3.0,
         "max_bars": 0, "trend_ema": 100},
        "Igual pero con filtro de tendencia propia, ajustada en velas de 1h. "
        "Gana en mercados bajistas pero se hunde en los alcistas: descartada.",
    ),
    "momentum": (
        MomentumBreakout, {},
        "Rotura de máximos con take-profit fijo. Configuración base original.",
    ),
    "meanrev": (
        MeanReversionRSI, {},
        "Compra caídas (RSI sobreventa) dentro de tendencia alcista.",
    ),
}

STRATEGIES = PRESETS  # compatibilidad


def make_strategy(name: str) -> Strategy:
    if name not in PRESETS:
        raise ValueError(f"Estrategia desconocida: {name}. Disponibles: {list(PRESETS)}")
    cls, kwargs, _ = PRESETS[name]
    strat = cls(**kwargs)
    strat.name = name          # el nombre del preset viaja a las operaciones
    return strat


def describe_strategies() -> list:
    return [{"name": n, "description": d} for n, (_, _, d) in PRESETS.items()]
