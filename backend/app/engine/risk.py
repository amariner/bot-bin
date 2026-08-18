"""Gestión de riesgo: tamaño de posición por riesgo fijo y circuit breaker diario."""
from typing import Optional

from ..config import settings

DAY_MS = 86_400_000


class RiskManager:
    def __init__(self, risk_per_trade: float = None, max_positions: int = None,
                 daily_max_loss_pct: float = None, max_notional_pct: float = None,
                 min_notional: float = None):
        self.risk_per_trade = settings.risk_per_trade if risk_per_trade is None else risk_per_trade
        self.max_positions = settings.max_positions if max_positions is None else max_positions
        self.daily_max_loss_pct = (settings.daily_max_loss_pct
                                   if daily_max_loss_pct is None else daily_max_loss_pct)
        self.max_notional_pct = (settings.max_position_notional_pct
                                 if max_notional_pct is None else max_notional_pct)
        self.min_notional = settings.min_notional if min_notional is None else min_notional
        self.day_start_ts: Optional[int] = None
        self.day_start_equity: Optional[float] = None
        self.halted = False

    def roll_day(self, ts_ms: int, equity: float):
        """Reinicia la referencia diaria a medianoche UTC; levanta el circuit breaker."""
        day = ts_ms - (ts_ms % DAY_MS)
        if self.day_start_ts != day:
            self.day_start_ts = day
            self.day_start_equity = equity
            self.halted = False

    def check_circuit_breaker(self, equity: float) -> bool:
        """True si hay que parar de operar hoy."""
        if self.day_start_equity is None or self.day_start_equity <= 0:
            return self.halted
        if equity <= self.day_start_equity * (1 - self.daily_max_loss_pct):
            self.halted = True
        return self.halted

    def daily_pnl_pct(self, equity: float) -> float:
        if not self.day_start_equity:
            return 0.0
        return (equity / self.day_start_equity - 1) * 100

    def position_notional(self, equity: float, entry: float, stop: float) -> Optional[float]:
        """Nocional (USDT) tal que si salta el stop se pierde ~risk_per_trade del equity.
        Devuelve None si la operación no es viable."""
        if entry <= 0 or stop <= 0 or stop >= entry:
            return None
        stop_dist_pct = (entry - stop) / entry
        if stop_dist_pct <= 0.0005:      # stop demasiado pegado: tamaño absurdo
            return None
        notional = equity * self.risk_per_trade / stop_dist_pct
        notional = min(notional, equity * self.max_notional_pct)
        if notional < self.min_notional:
            return None
        return notional

    def can_open(self, open_positions: int, cash: float, notional: float) -> bool:
        if self.halted:
            return False
        if open_positions >= self.max_positions:
            return False
        return cash >= notional
