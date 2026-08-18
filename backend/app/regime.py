"""Filtro de régimen de mercado.

En cripto casi todas las altcoins están correlacionadas con BTC: los breakouts
alcistas fallan mucho más cuando BTC está por debajo de su media. Este filtro
permite al motor abrir posiciones solo en régimen "risk-on".
"""
import bisect
from typing import Dict, List, Optional

from .indicators import ema_series
from .models import Candle


class MarketRegime:
    """Estado risk-on/risk-off derivado de BTC vs su EMA."""

    def __init__(self, btc_candles: Optional[List[Candle]] = None, ema_period: int = 50):
        self.ema_period = ema_period
        self._ts: List[int] = []
        self._flags: List[bool] = []
        if btc_candles:
            self.rebuild(btc_candles)

    def rebuild(self, btc_candles: List[Candle]):
        closes = [c.close for c in btc_candles]
        emas = ema_series(closes, self.ema_period)
        self._ts = []
        self._flags = []
        for c, e in zip(btc_candles, emas):
            if e is None:
                continue
            self._ts.append(c.ts)
            self._flags.append(c.close > e)

    def is_risk_on(self, ts: int) -> bool:
        """Régimen vigente en `ts` (usa el último cierre de BTC conocido).
        Sin datos suficientes devolvemos True para no bloquear el arranque."""
        if not self._ts:
            return True
        i = bisect.bisect_right(self._ts, ts) - 1
        if i < 0:
            return True
        return self._flags[i]
