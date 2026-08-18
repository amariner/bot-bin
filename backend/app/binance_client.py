"""Cliente REST de Binance: datos públicos (sin clave) y órdenes en testnet (con clave)."""
import asyncio
import hashlib
import hmac
import logging
import time
from typing import List, Optional
from urllib.parse import urlencode

import httpx

from .config import settings
from .models import Candle


log = logging.getLogger("binance")


class BinancePublic:
    """Endpoints públicos del mercado real (solo lectura)."""

    def __init__(self, base: Optional[str] = None, max_retries: int = 4):
        self.base = base or settings.rest_base
        self.max_retries = max_retries
        # trust_env=False: en macOS corporativo httpx heredaría el proxy del
        # sistema (que devuelve 407). Conexión directa, como hace curl.
        self._client = httpx.AsyncClient(base_url=self.base, timeout=20.0,
                                         trust_env=settings.trust_env_proxy)

    async def close(self):
        await self._client.aclose()

    async def _get(self, path: str, params: Optional[dict] = None):
        """GET con reintentos: proxies corporativos y rate limits devuelven
        errores transitorios (407/429/5xx) que no deben tumbar el arranque."""
        delay = 1.0
        last_error = None
        for attempt in range(self.max_retries):
            try:
                r = await self._client.get(path, params=params)
                if r.status_code in (407, 408, 425, 429, 500, 502, 503, 504):
                    raise httpx.HTTPStatusError(f"HTTP {r.status_code}",
                                                request=r.request, response=r)
                r.raise_for_status()
                return r.json()
            except (httpx.HTTPStatusError, httpx.TransportError) as e:
                last_error = e
                if attempt == self.max_retries - 1:
                    break
                log.warning("reintento %d/%d en %s: %s", attempt + 1,
                            self.max_retries, path, e)
                await asyncio.sleep(delay)
                delay = min(delay * 2, 8.0)
        raise last_error

    async def ticker_24h(self) -> List[dict]:
        return await self._get("/api/v3/ticker/24hr")

    async def exchange_info(self) -> dict:
        return await self._get("/api/v3/exchangeInfo")

    async def klines(self, symbol: str, interval: str, limit: int = 500,
                     start_ms: Optional[int] = None, end_ms: Optional[int] = None) -> List[Candle]:
        params = {"symbol": symbol, "interval": interval, "limit": limit}
        if start_ms is not None:
            params["startTime"] = start_ms
        if end_ms is not None:
            params["endTime"] = end_ms
        return [Candle.from_kline(k) for k in await self._get("/api/v3/klines", params)]


class BinanceTestnet:
    """Órdenes firmadas contra el Spot Testnet. Solo para smoke test de integración —
    la validación de estrategia se hace con el motor de paper trading sobre datos reales."""

    def __init__(self, api_key: str = "", api_secret: str = ""):
        self.api_key = api_key or settings.testnet_api_key
        self.api_secret = api_secret or settings.testnet_api_secret
        self._client = httpx.AsyncClient(base_url=settings.testnet_rest_base, timeout=20.0,
                                         trust_env=settings.trust_env_proxy)

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.api_secret)

    def _sign(self, params: dict) -> dict:
        params = dict(params)
        params["timestamp"] = int(time.time() * 1000)
        query = urlencode(params)
        params["signature"] = hmac.new(
            self.api_secret.encode(), query.encode(), hashlib.sha256
        ).hexdigest()
        return params

    async def account(self) -> dict:
        r = await self._client.get("/api/v3/account", params=self._sign({}),
                                   headers={"X-MBX-APIKEY": self.api_key})
        r.raise_for_status()
        return r.json()

    async def market_order(self, symbol: str, side: str, quote_qty: float) -> dict:
        params = self._sign({
            "symbol": symbol, "side": side.upper(), "type": "MARKET",
            "quoteOrderQty": round(quote_qty, 2),
        })
        r = await self._client.post("/api/v3/order", params=params,
                                    headers={"X-MBX-APIKEY": self.api_key})
        r.raise_for_status()
        return r.json()

    async def close(self):
        await self._client.aclose()
