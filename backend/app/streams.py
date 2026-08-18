"""Stream de mercado de Binance por websocket con reconexión automática.

Se suscribe a las velas (kline) del timeframe configurado para todo el universo
y al miniTicker global para precios al tick. Entrega los mensajes por callbacks.
"""
import asyncio
import json
import logging
from typing import Awaitable, Callable, List, Optional

import websockets

from .config import settings

log = logging.getLogger("streams")


class MarketStream:
    def __init__(self, symbols: List[str], timeframe: Optional[str] = None,
                 on_kline_closed: Optional[Callable[[str, list], Awaitable[None]]] = None,
                 on_price: Optional[Callable[[str, float], Awaitable[None]]] = None):
        self.symbols = [s.lower() for s in symbols]
        self.timeframe = timeframe or settings.timeframe
        self.on_kline_closed = on_kline_closed
        self.on_price = on_price
        self._stop = asyncio.Event()
        self.connected = False

    async def run(self):
        """Bucle principal con reconexión exponencial."""
        backoff = 1
        while not self._stop.is_set():
            try:
                await self._session()
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as e:
                self.connected = False
                if self._stop.is_set():
                    break
                log.warning("stream caído (%s), reconectando en %ss", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60)

    async def _session(self):
        url = f"{settings.ws_base}/stream"
        async with websockets.connect(url, ping_interval=180, ping_timeout=600,
                                      max_size=2 ** 22) as ws:
            streams = [f"{s}@kline_{self.timeframe}" for s in self.symbols]
            streams.append("!miniTicker@arr")
            # SUBSCRIBE en bloques de 100 (límite de Binance por mensaje)
            for i in range(0, len(streams), 100):
                await ws.send(json.dumps({
                    "method": "SUBSCRIBE",
                    "params": streams[i:i + 100],
                    "id": i + 1,
                }))
                await asyncio.sleep(0.3)
            self.connected = True
            log.info("suscrito a %d streams", len(streams))

            while not self._stop.is_set():
                raw = await asyncio.wait_for(ws.recv(), timeout=300)
                msg = json.loads(raw)
                data = msg.get("data")
                if data is None:
                    continue
                await self._dispatch(data)

    async def _dispatch(self, data):
        if isinstance(data, list):  # !miniTicker@arr
            if self.on_price:
                wanted = set(self.symbols)
                for t in data:
                    sym = t.get("s", "").lower()
                    if sym in wanted:
                        await self.on_price(t["s"], float(t["c"]))
            return
        if data.get("e") == "kline":
            k = data["k"]
            if k["x"] and self.on_kline_closed:  # solo velas cerradas
                # mismo orden que el kline REST para reutilizar Candle.from_kline
                await self.on_kline_closed(data["s"], [
                    k["t"], k["o"], k["h"], k["l"], k["c"], k["v"], k["T"], k["q"],
                ])

    def stop(self):
        self._stop.set()
