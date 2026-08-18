"""Selección del universo operable: top-N pares USDT por volumen 24h en Binance,
excluyendo stablecoins y tokens apalancados."""
import re
from typing import List, Optional

from .binance_client import BinancePublic
from .config import settings, STABLE_BASES

_LEVERAGED = re.compile(r"(UP|DOWN|BULL|BEAR)$")


def filter_universe(tickers: List[dict], trading_symbols: set, size: int) -> List[dict]:
    """Lógica pura para poder testearla: recibe tickers 24h y símbolos en estado TRADING."""
    quote = settings.quote_asset
    rows = []
    for t in tickers:
        sym = t["symbol"]
        if not sym.endswith(quote):
            continue
        base = sym[: -len(quote)]
        if base in STABLE_BASES or _LEVERAGED.search(base):
            continue
        if sym not in trading_symbols:
            continue
        rows.append({
            "symbol": sym,
            "base": base,
            "last_price": float(t["lastPrice"]),
            "change_pct": float(t["priceChangePercent"]),
            "quote_volume": float(t["quoteVolume"]),
        })
    rows.sort(key=lambda r: r["quote_volume"], reverse=True)
    return rows[:size]


async def fetch_universe(client: BinancePublic, size: Optional[int] = None) -> List[dict]:
    size = size or settings.universe_size
    info = await client.exchange_info()
    trading = {s["symbol"] for s in info["symbols"] if s["status"] == "TRADING"}
    tickers = await client.ticker_24h()
    return filter_universe(tickers, trading, size)
