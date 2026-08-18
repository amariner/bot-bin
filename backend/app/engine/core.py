"""Motor de ejecución compartido por backtest y trading en vivo.

La misma lógica de entradas, stops, take-profits y riesgo procesa velas cerradas
en ambos modos: lo que se backtestea es exactamente lo que corre en vivo.
"""
from dataclasses import asdict, fields
from typing import Dict, List, Optional

from ..config import settings
from ..models import Candle, Position, Trade
from ..strategy.base import Strategy
from .paper import PaperBroker
from .risk import RiskManager


class TradingEngine:
    def __init__(self, strategy: Strategy, capital: float = None,
                 broker: PaperBroker = None, risk: RiskManager = None,
                 regime=None):
        self.strategy = strategy
        self.cash = settings.initial_capital if capital is None else capital
        self.initial_capital = self.cash
        self.broker = broker or PaperBroker()
        self.risk = risk or RiskManager()
        self.regime = regime            # MarketRegime opcional (filtro BTC)
        self.positions: Dict[str, Position] = {}
        self.trades: List[Trade] = []
        self.last_prices: Dict[str, float] = {}
        # contadores de diagnóstico para la UI
        self.candles_processed = 0
        self.signals_seen = 0
        self.signals_rejected_risk = 0
        self.signals_rejected_regime = 0
        self.last_candle_ts: Optional[int] = None

    # ------------------------------------------------------------------ estado

    def equity(self) -> float:
        eq = self.cash
        for sym, pos in self.positions.items():
            price = self.last_prices.get(sym, pos.entry_price)
            eq += pos.qty * price
        return eq

    # ------------------------------------------------------------- ciclo velas

    def on_candle_closed(self, symbol: str, candles: List[Candle]) -> List[dict]:
        """Procesa la última vela CERRADA de `symbol`. Devuelve eventos ocurridos."""
        events: List[dict] = []
        last = candles[-1]
        self.last_prices[symbol] = last.close
        self.candles_processed += 1
        self.last_candle_ts = last.ts
        self.risk.roll_day(last.ts, self.equity())

        exited_now = False
        pos = self.positions.get(symbol)
        if pos is not None:
            pos.bars_held += 1
            # 1) Salidas con el stop vigente (fijado al cierre de la vela anterior)
            exit_price, reason = self._check_exit(pos, last, candles)
            if exit_price is not None:
                events.append(self._close_position(pos, exit_price, last.ts + 1, reason))
                exited_now = True
            else:
                # 2) Solo si sigue abierta movemos el trailing, que regirá a
                #    partir de la SIGUIENTE vela. Evita sesgo intrabar.
                self.strategy.update_position(symbol, candles, pos)

        # Circuit breaker: con pérdida diaria excedida no se abren posiciones nuevas
        if self.risk.check_circuit_breaker(self.equity()):
            return events

        # No reentramos en la misma vela en la que acabamos de cerrar
        if symbol not in self.positions and not exited_now:
            ev = self._try_entry(symbol, candles)
            if ev:
                events.append(ev)
        return events

    def _check_exit(self, pos: Position, candle: Candle, candles: List[Candle]):
        """SL/TP intrabar (conservador: si la vela toca ambos, asumimos stop primero),
        luego salida de estrategia, luego stop temporal."""
        if candle.low <= pos.stop_price:
            return pos.stop_price, "stop-loss"
        if candle.high >= pos.take_profit:
            return pos.take_profit, "take-profit"
        strat_reason = self.strategy.check_exit(pos.symbol, candles, pos)
        if strat_reason:
            return candle.close, strat_reason
        max_bars = getattr(self.strategy, "max_bars", 0)
        if max_bars and pos.bars_held >= max_bars:
            return candle.close, f"tiempo ({pos.bars_held} velas)"
        return None, None

    def _try_entry(self, symbol: str, candles: List[Candle]) -> Optional[dict]:
        signal = self.strategy.check_entry(symbol, candles)
        if signal is None:
            return None
        self.signals_seen += 1

        def skipped(reason: str) -> dict:
            return {"type": "signal_skipped", "symbol": symbol, "reason": reason,
                    "signal_reason": signal.reason}

        if self.regime is not None and not self.regime.is_risk_on(candles[-1].ts):
            self.signals_rejected_regime += 1
            return skipped("régimen BTC bajista")
        notional = self.risk.position_notional(self.equity(), signal.entry_price, signal.stop_price)
        if notional is None:
            self.signals_rejected_risk += 1
            return skipped("tamaño inviable (stop demasiado cerca o bajo el mínimo)")
        if self.risk.halted:
            self.signals_rejected_risk += 1
            return skipped("circuit breaker diario activo")
        if len(self.positions) >= self.risk.max_positions:
            self.signals_rejected_risk += 1
            return skipped(f"sin huecos ({len(self.positions)}/{self.risk.max_positions} posiciones)")
        if self.cash < notional:
            self.signals_rejected_risk += 1
            return skipped("efectivo insuficiente")
        fill = self.broker.buy(notional, signal.entry_price)
        self.cash -= fill.notional + fill.fee
        pos = Position(
            symbol=symbol, qty=fill.qty, entry_price=fill.price,
            stop_price=signal.stop_price, take_profit=signal.take_profit,
            opened_ts=candles[-1].ts, strategy=self.strategy.name,
            reason=signal.reason, entry_fee=fill.fee,
        )
        self.positions[symbol] = pos
        return {"type": "open", "position": pos.to_dict(fill.price)}

    def _close_position(self, pos: Position, market_price: float, ts: int, reason: str) -> dict:
        fill = self.broker.sell(pos.qty, market_price)
        self.cash += fill.notional - fill.fee
        fees = pos.entry_fee + fill.fee
        pnl = (fill.price - pos.entry_price) * pos.qty - fees
        trade = Trade(
            symbol=pos.symbol, side="long", qty=pos.qty,
            entry_price=pos.entry_price, exit_price=fill.price,
            entry_ts=pos.opened_ts, exit_ts=ts,
            pnl=round(pnl, 6), fees=round(fees, 6),
            strategy=pos.strategy, entry_reason=pos.reason, exit_reason=reason,
        )
        self.trades.append(trade)
        del self.positions[pos.symbol]
        return {"type": "close", "trade": trade.to_dict()}

    def check_tick_exit(self, symbol: str, price: float, ts: int) -> Optional[dict]:
        """En vivo, los stops se vigilan al tick (no solo al cierre de vela) para
        replicar el supuesto intrabar del backtest."""
        self.last_prices[symbol] = price
        pos = self.positions.get(symbol)
        if pos is None:
            return None
        if price <= pos.stop_price:
            return self._close_position(pos, price, ts, "stop-loss")
        if price >= pos.take_profit:
            return self._close_position(pos, price, ts, "take-profit")
        return None

    # ------------------------------------------------- persistencia de estado

    STATE_VERSION = 1

    def to_state(self) -> dict:
        """Foto completa del motor. Se guarda como un único JSON para que la
        escritura sea atómica: o se guarda todo, o no se guarda nada. Nunca
        puede quedar medio estado tras una caída."""
        return {
            "version": self.STATE_VERSION,
            "strategy": self.strategy.name,
            "cash": self.cash,
            "initial_capital": self.initial_capital,
            "positions": [asdict(p) for p in self.positions.values()],
            "risk": {
                "day_start_ts": self.risk.day_start_ts,
                "day_start_equity": self.risk.day_start_equity,
                "halted": self.risk.halted,
            },
            "counters": {
                "candles_processed": self.candles_processed,
                "signals_seen": self.signals_seen,
                "signals_rejected_risk": self.signals_rejected_risk,
                "signals_rejected_regime": self.signals_rejected_regime,
            },
        }

    def restore_state(self, st: dict) -> int:
        """Reconstruye el motor desde una foto previa. Devuelve el número de
        posiciones recuperadas. Tolera estados de versiones anteriores."""
        if not st or st.get("version") != self.STATE_VERSION:
            return 0
        self.cash = float(st["cash"])
        self.initial_capital = float(st.get("initial_capital", self.initial_capital))
        self.positions = {}
        # Solo se aceptan los campos que Position tiene HOY. Así, si en una
        # actualización futura se añade o se quita un campo, el estado antiguo
        # se sigue leyendo en vez de reventar el arranque.
        valid = {f.name for f in fields(Position)}
        for d in st.get("positions", []):
            data = {k: v for k, v in d.items() if k in valid}
            data.setdefault("meta", {})
            pos = Position(**data)
            self.positions[pos.symbol] = pos
            # sin precio de mercado todavía, el equity parte del de entrada
            self.last_prices.setdefault(pos.symbol, pos.entry_price)
        r = st.get("risk") or {}
        self.risk.day_start_ts = r.get("day_start_ts")
        self.risk.day_start_equity = r.get("day_start_equity")
        self.risk.halted = bool(r.get("halted"))
        c = st.get("counters") or {}
        self.candles_processed = c.get("candles_processed", 0)
        self.signals_seen = c.get("signals_seen", 0)
        self.signals_rejected_risk = c.get("signals_rejected_risk", 0)
        self.signals_rejected_regime = c.get("signals_rejected_regime", 0)
        return len(self.positions)

    def liquidate_all(self, ts: int, reason: str = "liquidación") -> List[dict]:
        events = []
        for sym in list(self.positions):
            pos = self.positions[sym]
            price = self.last_prices.get(sym, pos.entry_price)
            events.append(self._close_position(pos, price, ts, reason))
        return events
