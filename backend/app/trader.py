"""Orquestador del trading en vivo (paper) sobre datos reales de Binance.

Al arrancar: selecciona el universo, precalienta el histórico de velas por REST,
se suscribe al websocket y procesa velas cerradas con el TradingEngine. Persiste
operaciones y equity en SQLite y difunde el estado a los clientes de la UI.
"""
import asyncio
import logging
import time
from collections import deque
from typing import Deque, Dict, List, Optional, Set

from .binance_client import BinancePublic
from .config import settings, TIMEFRAME_MS
from .db import Database
from .engine.core import TradingEngine
from .models import Candle
from .regime import MarketRegime
from .strategy import make_strategy
from .streams import MarketStream
from .universe import fetch_universe

log = logging.getLogger("trader")


class LiveTrader:
    def __init__(self, db: Database, strategy_name: Optional[str] = None,
                 capital: Optional[float] = None):
        self.db = db
        self.strategy_name = strategy_name or settings.default_strategy
        self.regime = MarketRegime(ema_period=settings.regime_ema) \
            if settings.use_regime_filter else None
        self.engine = TradingEngine(make_strategy(self.strategy_name), capital=capital,
                                    regime=self.regime)
        self.client = BinancePublic()
        self.candles: Dict[str, Deque[Candle]] = {}
        self.universe: List[dict] = []
        self.ticker: Dict[str, dict] = {}
        self.stream: Optional[MarketStream] = None
        self.status = "stopped"          # stopped | warming_up | running | error
        self.error: Optional[str] = None
        self.started_at: Optional[int] = None
        self.recent_events: Deque[dict] = deque(maxlen=80)
        # Cotización EUR/USDT para poder mostrar el equivalente en euros.
        # Se opera en USDT (es donde está la liquidez), pero el usuario piensa en €.
        self.eur_rate: Optional[float] = None
        self._tasks: List[asyncio.Task] = []
        self._subscribers: Set[asyncio.Queue] = set()
        self._last_broadcast = 0.0

    # ------------------------------------------------------------- ciclo vida

    async def start(self):
        if self.status in ("running", "warming_up"):
            return
        self.status = "warming_up"
        self.error = None
        self.started_at = int(time.time() * 1000)

        # 1) Recuperar el estado anterior ANTES de nada: si el proceso se cayó
        #    con monedas compradas, hay que seguir vigilándolas aunque ya no
        #    estén entre las 100 de mayor volumen.
        restored = self._restore_state()

        try:
            self.universe = await fetch_universe(self.client)
            for row in self.universe:
                self.ticker[row["symbol"]] = row
            await self._warmup()
        except Exception as e:
            self.status = "error"
            self.error = f"arranque fallido: {e}"
            log.exception("arranque fallido")
            return

        symbols = [r["symbol"] for r in self.universe]
        # Monedas recuperadas que ya no están en el universo: se vigilan igual,
        # porque hay dinero dentro y su stop tiene que poder ejecutarse.
        for sym in self.engine.positions:
            if sym not in symbols:
                symbols.append(sym)
                log.warning("posición recuperada fuera del universo: %s", sym)
        # BTC hace falta para el filtro de régimen aunque no sea operable
        if self.regime is not None and "BTCUSDT" not in symbols:
            symbols.append("BTCUSDT")
        # EURUSDT solo para convertir a euros en la interfaz, nunca se opera
        if "EURUSDT" not in symbols:
            symbols.append("EURUSDT")
        self.stream = MarketStream(symbols, on_kline_closed=self._on_kline,
                                   on_price=self._on_price)
        self._tasks = [
            asyncio.create_task(self.stream.run()),
            asyncio.create_task(self._snapshot_loop()),
        ]
        self.status = "running"
        self._persist_event({"type": "start", "strategy": self.strategy_name,
                             "universe": len(symbols), "capital": self.engine.cash,
                             "restored": restored})
        self._save_state()
        await self.broadcast(force=True)

    async def _warmup(self):
        """Descarga las últimas velas de cada símbolo para que las estrategias
        tengan histórico desde el primer minuto (EMA200 incluida)."""
        sem = asyncio.Semaphore(8)

        async def fetch(sym: str):
            async with sem:
                cs = await self.client.klines(sym, settings.timeframe,
                                              limit=settings.candle_history)
                if cs:
                    cs.pop()  # la última puede estar sin cerrar
                self.candles[sym] = deque(cs, maxlen=settings.candle_history)

        # el universo más las monedas ya compradas (que pueden haber salido de él)
        wanted = {r["symbol"] for r in self.universe} | set(self.engine.positions)
        await asyncio.gather(*(fetch(s) for s in wanted))

        # El filtro de régimen necesita histórico de BTC aunque BTC no esté
        # en el universo operable
        try:
            self.eur_rate = await self.client.price("EURUSDT")
        except Exception:
            self.eur_rate = None       # sin cambio a euros la UI sigue funcionando

        if self.regime is not None:
            btc = list(self.candles.get("BTCUSDT") or
                       await self.client.klines("BTCUSDT", settings.timeframe,
                                                limit=settings.candle_history))
            self.regime.rebuild(btc)
            log.info("régimen BTC: %s", "risk-on" if self.regime.is_risk_on(
                int(time.time() * 1000)) else "risk-off")
        log.info("warmup completo: %d símbolos", len(self.candles))

    async def stop(self, liquidate: bool = False):
        if self.stream:
            self.stream.stop()
        for t in self._tasks:
            t.cancel()
        self._tasks = []
        if liquidate:
            now = int(time.time() * 1000)
            for ev in self.engine.liquidate_all(now, "parada manual"):
                self._persist_event(ev)
        self.status = "stopped"
        self._save_state()
        self._persist_event({"type": "stop"})
        await self.broadcast(force=True)

    # ---------------------------------------------------------------- mercado

    async def _on_kline(self, symbol: str, kline: list):
        candle = Candle.from_kline(kline)
        dq = self.candles.setdefault(symbol, deque(maxlen=settings.candle_history))
        if dq and dq[-1].ts == candle.ts:
            dq[-1] = candle
        else:
            dq.append(candle)
        # Al cerrar una vela de BTC, recalculamos el régimen de mercado
        if symbol == "BTCUSDT" and self.regime is not None:
            self.regime.rebuild(list(dq))
        events = self.engine.on_candle_closed(symbol, list(dq))
        for ev in events:
            self._persist_event(ev)
        # el trailing se mueve en cada vela aunque no haya evento: hay que
        # guardarlo o un reinicio devolvería el stop a una posición antigua
        self._save_state()
        if events:
            await self.broadcast(force=True)

    async def _on_price(self, symbol: str, price: float):
        if symbol == "EURUSDT":
            self.eur_rate = price      # solo referencia de cambio, no se opera
            return
        if symbol in self.ticker:
            self.ticker[symbol]["last_price"] = price
        ev = self.engine.check_tick_exit(symbol, price, int(time.time() * 1000))
        if ev:
            self._persist_event(ev)
            self._save_state()
            await self.broadcast(force=True)
        else:
            await self.broadcast()  # rate-limited

    # ------------------------------------------------ estado que sobrevive

    STATE_KEY = "engine_state"

    def _save_state(self):
        """Escritura atómica del estado completo. Se llama tras cada cambio
        relevante, así que una caída pierde como mucho lo ocurrido entre dos
        eventos, nunca deja el estado a medias."""
        try:
            st = self.engine.to_state()
            st["saved_at"] = int(time.time() * 1000)
            st["timeframe"] = settings.timeframe
            self.db.set_kv(self.STATE_KEY, st)
        except Exception:
            log.exception("no se pudo guardar el estado")

    def _restore_state(self) -> int:
        """Devuelve cuántas posiciones se han recuperado."""
        try:
            st = self.db.get_kv(self.STATE_KEY)
        except Exception:
            log.exception("no se pudo leer el estado guardado")
            return 0
        if not st:
            log.info("sin estado previo: arranque limpio")
            return 0
        if st.get("strategy") != self.strategy_name:
            log.warning("el estado guardado es de la estrategia '%s' y ahora se usa "
                        "'%s'; se recuperan las posiciones igualmente (hay dinero dentro)",
                        st.get("strategy"), self.strategy_name)
        n = self.engine.restore_state(st)
        age_min = (int(time.time() * 1000) - st.get("saved_at", 0)) / 60000
        log.info("estado recuperado: %d posiciones, %.2f USDT libres, guardado hace %.0f min",
                 n, self.engine.cash, age_min)
        return n

    def _persist_event(self, ev: dict):
        now = int(time.time() * 1000)
        if ev["type"] == "close":
            self.db.insert_trade(ev["trade"])
        text = self._describe_event(ev)
        # el texto legible viaja también a SQLite para que el feed sobreviva reinicios
        self.db.insert_event(now, ev["type"], {**ev, "text": text})
        self.recent_events.appendleft({"ts": now, "type": ev["type"], "text": text})
        log.info("evento: %s", text)

    @staticmethod
    def _describe_event(ev: dict) -> str:
        """Texto legible para el feed de actividad de la UI."""
        t = ev["type"]
        if t == "open":
            p = ev["position"]
            notional = p["qty"] * p["entry_price"]
            return (f"COMPRA {p['symbol']}: {notional:,.0f} $ a {p['entry_price']:.6g} "
                    f"({p['reason']}) · stop {p['stop_price']:.6g}")
        if t == "close":
            tr = ev["trade"]
            return (f"VENTA {tr['symbol']}: {tr['pnl']:+,.2f} $ "
                    f"({tr['exit_reason']}) · entrada {tr['entry_price']:.6g} "
                    f"→ salida {tr['exit_price']:.6g}")
        if t == "signal_skipped":
            return (f"Señal en {ev['symbol']} ({ev['signal_reason']}) "
                    f"descartada: {ev['reason']}")
        if t == "start":
            return (f"Bot arrancado: {ev.get('strategy')} sobre "
                    f"{ev.get('universe')} pares, capital {ev.get('capital'):,.0f} $")
        if t == "stop":
            return "Bot parado"
        return t

    async def _snapshot_loop(self):
        while True:
            await asyncio.sleep(30)
            now = int(time.time() * 1000)
            self.db.insert_equity(now, self.engine.equity(), self.engine.cash,
                                  len(self.engine.positions))
            self._save_state()   # red de seguridad periódica

    # ---------------------------------------------------------------- estado UI

    def near_signals(self, max_rows: int = 8) -> List[dict]:
        """Monedas a punto de cumplir la condición de entrada: qué vigila el bot.

        Mide, con las velas CERRADAS, cuánto le falta al precio para superar el
        máximo de las últimas 20 velas y cómo va el volumen frente al 4x exigido.
        """
        strat = self.engine.strategy
        lookback = getattr(strat, "lookback", 20)
        vol_mult = getattr(strat, "vol_mult", 4.0)
        rows = []
        for sym, dq in self.candles.items():
            if len(dq) < lookback + 2:
                continue
            candles = list(dq)
            window = candles[-lookback - 1:-1]
            last = candles[-1]
            prev_high = max(c.high for c in window)
            avg_vol = sum(c.volume for c in window) / lookback
            if prev_high <= 0 or avg_vol <= 0:
                continue
            dist_pct = (prev_high - last.close) / prev_high * 100
            if dist_pct > 3.0:          # lejos de rotura: no interesa
                continue
            rows.append({
                "symbol": sym,
                "dist_to_breakout_pct": round(dist_pct, 2),
                "breakout_level": prev_high,
                "last_close": last.close,
                "vol_ratio": round(last.volume / avg_vol, 2),
                "vol_needed": vol_mult,
                "in_position": sym in self.engine.positions,
            })
        rows.sort(key=lambda r: r["dist_to_breakout_pct"])
        return rows[:max_rows]

    def weekly_movers(self, days: int = 7) -> List[dict]:
        """Variación de los últimos `days` días por moneda.

        No hace falta pedir nada a Binance: el bot ya guarda en memoria 300
        velas por símbolo, así que basta con comparar el precio actual con el
        cierre de hace una semana.
        """
        tf_ms = TIMEFRAME_MS.get(settings.timeframe, 300_000)
        needed = int(days * 86_400_000 / tf_ms)
        rows = []
        for sym, dq in self.candles.items():
            if sym == "EURUSDT" or len(dq) < needed + 1:
                continue
            candles = list(dq)
            past = candles[-(needed + 1)].close
            info = self.ticker.get(sym, {})
            last = info.get("last_price") or candles[-1].close
            if past <= 0:
                continue
            rows.append({
                "symbol": sym,
                "base": sym[:-4] if sym.endswith("USDT") else sym,
                "last_price": last,
                "change_pct": round((last / past - 1) * 100, 2),
                "quote_volume": info.get("quote_volume", 0.0),
            })
        rows.sort(key=lambda r: r["change_pct"], reverse=True)
        return rows

    def state_snapshot(self) -> dict:
        eng = self.engine
        equity = eng.equity()
        movers = sorted(self.ticker.values(), key=lambda r: r["change_pct"], reverse=True)
        weekly = self.weekly_movers() if self.status == "running" else []
        tf_ms = TIMEFRAME_MS.get(settings.timeframe, 300_000)
        now_ms = int(time.time() * 1000)
        return {
            "type": "state",
            "ts": now_ms,
            "status": self.status,
            "error": self.error,
            "strategy": self.strategy_name,
            "started_at": self.started_at,
            "stream_connected": bool(self.stream and self.stream.connected),
            # diagnóstico: para saber que el bot está vivo aunque no opere
            "timeframe": settings.timeframe,
            "next_close_ts": (now_ms - now_ms % tf_ms) + tf_ms,
            "candles_processed": eng.candles_processed,
            "signals_seen": eng.signals_seen,
            "signals_rejected": eng.signals_rejected_risk + eng.signals_rejected_regime,
            "last_candle_ts": eng.last_candle_ts,
            "regime_filter": self.regime is not None,
            "regime_risk_on": (self.regime.is_risk_on(now_ms)
                               if self.regime is not None else None),
            "equity": round(equity, 2),
            "cash": round(eng.cash, 2),
            "initial_capital": eng.initial_capital,
            "total_return_pct": round((equity / eng.initial_capital - 1) * 100, 3),
            "daily_pnl_pct": round(eng.risk.daily_pnl_pct(equity), 3),
            "circuit_breaker": eng.risk.halted,
            "open_positions": [p.to_dict(eng.last_prices.get(s)) for s, p in eng.positions.items()],
            "session_trades": [t.to_dict() for t in eng.trades[-50:]],
            "universe_size": len(self.universe),
            "top_movers": movers[:12],
            "bottom_movers": movers[-6:][::-1] if len(movers) > 6 else [],
            "weekly_top": weekly[:12],
            "weekly_bottom": weekly[-6:][::-1] if len(weekly) > 6 else [],
            "eur_rate": self.eur_rate,
            "recent_events": list(self.recent_events)[:40],
            "near_signals": self.near_signals() if self.status == "running" else [],
            "max_positions": self.engine.risk.max_positions,
        }

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue):
        self._subscribers.discard(q)

    async def broadcast(self, force: bool = False):
        now = time.monotonic()
        if not force and now - self._last_broadcast < 1.0:   # máx 1 msg/s salvo eventos
            return
        self._last_broadcast = now
        state = self.state_snapshot()
        for q in list(self._subscribers):
            try:
                q.put_nowait(state)
            except asyncio.QueueFull:
                pass
