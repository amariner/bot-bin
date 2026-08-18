"""Descarga y caché local de velas históricas de Binance (CSV por símbolo)."""
import csv
import os
import time
from typing import List

from ..binance_client import BinancePublic
from ..config import settings, TIMEFRAME_MS
from ..models import Candle


def cache_path(symbol: str, interval: str) -> str:
    return os.path.join(settings.data_dir, f"{symbol}_{interval}.csv")


def save_candles(symbol: str, interval: str, candles: List[Candle]):
    os.makedirs(settings.data_dir, exist_ok=True)
    with open(cache_path(symbol, interval), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["ts", "open", "high", "low", "close", "volume"])
        for c in candles:
            w.writerow([c.ts, c.open, c.high, c.low, c.close, c.volume])


def load_candles(symbol: str, interval: str) -> List[Candle]:
    path = cache_path(symbol, interval)
    if not os.path.exists(path):
        return []
    out = []
    with open(path) as f:
        for row in csv.DictReader(f):
            out.append(Candle(ts=int(row["ts"]), open=float(row["open"]),
                              high=float(row["high"]), low=float(row["low"]),
                              close=float(row["close"]), volume=float(row["volume"])))
    return out


async def download_history(client: BinancePublic, symbol: str, interval: str,
                           days: int, use_cache: bool = True) -> List[Candle]:
    """Descarga `days` días de velas en tramos de 1000, con caché en disco."""
    if use_cache:
        cached = load_candles(symbol, interval)
        if cached:
            span_ms = days * 86_400_000
            now = int(time.time() * 1000)
            if cached[0].ts <= now - span_ms + TIMEFRAME_MS[interval] * 10 and \
               cached[-1].ts >= now - TIMEFRAME_MS[interval] * 20:
                return cached

    tf_ms = TIMEFRAME_MS[interval]
    end = int(time.time() * 1000)
    start = end - days * 86_400_000
    candles: List[Candle] = []
    cursor = start
    while cursor < end:
        batch = await client.klines(symbol, interval, limit=1000, start_ms=cursor)
        if not batch:
            break
        candles.extend(batch)
        cursor = batch[-1].ts + tf_ms
        if len(batch) < 1000:
            break
    # descartamos la última vela si aún está abierta
    if candles and candles[-1].ts + tf_ms > int(time.time() * 1000):
        candles.pop()
    save_candles(symbol, interval, candles)
    return candles
