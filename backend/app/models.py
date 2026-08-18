"""Tipos de dominio compartidos por backtest y trading en vivo."""
from dataclasses import dataclass, field, asdict
from typing import Optional


@dataclass
class Candle:
    ts: int          # apertura de la vela, epoch ms
    open: float
    high: float
    low: float
    close: float
    volume: float    # volumen en quote (USDT)

    @classmethod
    def from_kline(cls, k: list) -> "Candle":
        # Formato kline REST de Binance: [openTime, open, high, low, close, volume, closeTime, quoteVolume, ...]
        return cls(ts=int(k[0]), open=float(k[1]), high=float(k[2]),
                   low=float(k[3]), close=float(k[4]), volume=float(k[7]))


@dataclass
class Signal:
    symbol: str
    entry_price: float
    stop_price: float
    take_profit: float
    reason: str
    max_bars: int = 0        # 0 = sin límite de tiempo


@dataclass
class Position:
    symbol: str
    qty: float
    entry_price: float
    stop_price: float
    take_profit: float
    opened_ts: int
    strategy: str
    reason: str
    entry_fee: float = 0.0
    bars_held: int = 0
    # Estado libre de la estrategia (p. ej. máximo alcanzado para el trailing)
    meta: dict = field(default_factory=dict)

    def unrealized_pnl(self, price: float) -> float:
        return (price - self.entry_price) * self.qty

    def to_dict(self, price: Optional[float] = None) -> dict:
        d = asdict(self)
        d.pop("meta", None)   # estado interno crudo, no interesa a la UI
        d["peak"] = self.meta.get("peak")   # máximo alcanzado (ancla del trailing)
        if price is not None:
            d["last_price"] = price
            d["unrealized_pnl"] = round(self.unrealized_pnl(price), 4)
            d["unrealized_pct"] = round((price / self.entry_price - 1) * 100, 3)
            if price > 0:
                # colchón hasta el stop: cuánto puede retroceder antes de vender
                d["stop_distance_pct"] = round((price - self.stop_price) / price * 100, 2)
        return d


@dataclass
class Trade:
    symbol: str
    side: str                # "long"
    qty: float
    entry_price: float
    exit_price: float
    entry_ts: int
    exit_ts: int
    pnl: float               # neto de comisiones
    fees: float
    strategy: str
    entry_reason: str
    exit_reason: str

    def to_dict(self) -> dict:
        return asdict(self)
