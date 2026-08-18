"""Momentum breakout intradía, con filtros de selectividad y salida configurable.

Entrada base: la vela cierra por encima del máximo de las N velas anteriores,
con volumen superior a `vol_mult` veces la media y vela alcista. La idea: en
cripto las roturas de rango con volumen tienden a continuar a corto plazo.

Filtros opcionales (para operar MENOS y mejor — las comisiones son el enemigo):
  trend_ema    : exige precio por encima de su propia EMA (tendencia del símbolo)
  min_atr_pct  : descarta mercados muertos (ATR/precio demasiado bajo)
  max_atr_pct  : descarta mercados en pánico/pump (ATR/precio disparado)
  min_breakout : exige que la rotura supere el máximo por un margen mínimo

Salida: stop inicial a `atr_stop`·ATR. Si `trail_atr` > 0 el stop pasa a ser un
chandelier (máximo alcanzado − trail_atr·ATR) que solo sube nunca baja; si no,
take-profit fijo a `atr_tp`·ATR. Más un stop temporal de `max_bars` velas.
"""
from typing import List, Optional

from ..indicators import atr, ema, highest, sma
from ..models import Candle, Position, Signal
from .base import Strategy


class MomentumBreakout(Strategy):
    name = "momentum"

    # Defaults = mejor configuración validada; ver CLAUDE.md
    def __init__(self, lookback: int = 20, atr_period: int = 14,
                 vol_mult: float = 2.5, atr_stop: float = 2.0, atr_tp: float = 3.0,
                 max_bars: int = 48, trail_atr: float = 0.0, trend_ema: int = 0,
                 min_atr_pct: float = 0.0, max_atr_pct: float = 0.0,
                 min_breakout: float = 0.0, exit_ema: int = 0):
        self.lookback = lookback
        self.atr_period = atr_period
        self.vol_mult = vol_mult
        self.atr_stop = atr_stop
        self.atr_tp = atr_tp
        self.max_bars = max_bars
        self.trail_atr = trail_atr
        self.trend_ema = trend_ema
        self.min_atr_pct = min_atr_pct
        self.max_atr_pct = max_atr_pct
        self.min_breakout = min_breakout
        self.exit_ema = exit_ema
        self.warmup = max(lookback, atr_period, trend_ema, exit_ema) + 5

    def check_entry(self, symbol: str, candles: List[Candle]) -> Optional[Signal]:
        if len(candles) < self.warmup:
            return None
        last = candles[-1]
        if last.close <= last.open:                     # exigimos vela alcista
            return None

        window = candles[-self.lookback - 1:-1]
        prev_high = highest([c.high for c in window], self.lookback)
        if prev_high is None or last.close <= prev_high * (1 + self.min_breakout):
            return None

        avg_vol = sma([c.volume for c in window], self.lookback)
        if avg_vol is None or avg_vol <= 0 or last.volume < self.vol_mult * avg_vol:
            return None

        a = atr(candles, self.atr_period)
        if a is None or a <= 0:
            return None

        atr_pct = a / last.close
        if self.min_atr_pct and atr_pct < self.min_atr_pct:
            return None
        if self.max_atr_pct and atr_pct > self.max_atr_pct:
            return None

        if self.trend_ema:
            e = ema([c.close for c in candles], self.trend_ema)
            if e is None or last.close <= e:
                return None

        # Con trailing o salida por EMA el take-profit fijo estorba: dejamos
        # correr al ganador. Valor finito inalcanzable (inf rompería el JSON).
        open_ended = self.trail_atr > 0 or self.exit_ema > 0
        tp = last.close * 1000 if open_ended else last.close + self.atr_tp * a
        return Signal(
            symbol=symbol,
            entry_price=last.close,
            stop_price=last.close - self.atr_stop * a,
            take_profit=tp,
            reason=f"rotura {self.lookback}v · vol {last.volume / avg_vol:.1f}x",
            max_bars=self.max_bars,
        )

    def check_exit(self, symbol: str, candles: List[Candle],
                   position: Position) -> Optional[str]:
        """Salida por pérdida de tendencia: se sale cuando el precio cierra bajo
        su EMA. A diferencia del trailing por ATR, aguanta los retrocesos
        normales de una subida sostenida."""
        if not self.exit_ema:
            return None
        e = ema([c.close for c in candles], self.exit_ema)
        if e is not None and candles[-1].close < e:
            return f"cierre bajo EMA{self.exit_ema}"
        return None

    def update_position(self, symbol: str, candles: List[Candle], position: Position) -> None:
        """Chandelier stop: se ancla al máximo alcanzado desde la entrada y solo sube."""
        if self.trail_atr <= 0:
            return
        a = atr(candles, self.atr_period)
        if a is None or a <= 0:
            return
        peak = max(position.meta.get("peak", position.entry_price), candles[-1].high)
        position.meta["peak"] = peak
        new_stop = peak - self.trail_atr * a
        if new_stop > position.stop_price:
            position.stop_price = new_stop
