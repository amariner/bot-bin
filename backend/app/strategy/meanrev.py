"""Reversión a la media con RSI.

Entrada: RSI(14) en sobreventa (<28) pero con el precio por encima de la EMA(200)
— compramos caídas bruscas dentro de una tendencia de fondo alcista, no cuchillos
cayendo en tendencia bajista.

Salida: stop a 2*ATR, take-profit a 2*ATR, salida anticipada si el RSI recupera
55 (la reversión ya ocurrió), stop temporal de 96 velas (8h en 5m).
"""
from typing import List, Optional

from ..indicators import atr, ema, rsi
from ..models import Candle, Position, Signal
from .base import Strategy


class MeanReversionRSI(Strategy):
    name = "meanrev"

    def __init__(self, rsi_period: int = 14, oversold: float = 28.0, recover: float = 55.0,
                 trend_ema: int = 200, atr_period: int = 14,
                 atr_stop: float = 2.0, atr_tp: float = 2.0, max_bars: int = 96):
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.recover = recover
        self.trend_ema = trend_ema
        self.atr_period = atr_period
        self.atr_stop = atr_stop
        self.atr_tp = atr_tp
        self.max_bars = max_bars
        self.warmup = trend_ema + 10

    def check_entry(self, symbol: str, candles: List[Candle]) -> Optional[Signal]:
        if len(candles) < self.warmup:
            return None
        closes = [c.close for c in candles]
        r = rsi(closes[-(self.rsi_period * 6):], self.rsi_period)
        if r is None or r >= self.oversold:
            return None
        trend = ema(closes, self.trend_ema)
        last = candles[-1]
        if trend is None or last.close <= trend:
            return None
        a = atr(candles, self.atr_period)
        if a is None or a <= 0:
            return None
        return Signal(
            symbol=symbol,
            entry_price=last.close,
            stop_price=last.close - self.atr_stop * a,
            take_profit=last.close + self.atr_tp * a,
            reason=f"RSI {r:.0f} sobre EMA{self.trend_ema}",
            max_bars=self.max_bars,
        )

    def check_exit(self, symbol: str, candles: List[Candle], position: Position) -> Optional[str]:
        closes = [c.close for c in candles]
        r = rsi(closes[-(self.rsi_period * 6):], self.rsi_period)
        if r is not None and r >= self.recover:
            return f"RSI recuperado {r:.0f}"
        return None
