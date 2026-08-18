from typing import List, Optional

from app.engine.core import TradingEngine
from app.engine.paper import PaperBroker
from app.engine.risk import RiskManager
from app.models import Candle, Signal
from app.strategy.base import Strategy


class AlwaysBuy(Strategy):
    """Estrategia de prueba: compra en la primera vela posible con stop -5% / tp +10%."""
    name = "test"
    warmup = 1
    max_bars = 0

    def check_entry(self, symbol: str, candles: List[Candle]) -> Optional[Signal]:
        last = candles[-1]
        return Signal(symbol=symbol, entry_price=last.close,
                      stop_price=last.close * 0.95, take_profit=last.close * 1.10,
                      reason="test")


def mk_candle(ts, o, h, l, c, v=1000.0):
    return Candle(ts=ts, open=o, high=h, low=l, close=c, volume=v)


def mk_engine(**risk_kw):
    defaults = dict(risk_per_trade=0.01, max_positions=5, daily_max_loss_pct=0.5,
                    max_notional_pct=0.20, min_notional=5.0)
    defaults.update(risk_kw)
    return TradingEngine(AlwaysBuy(), capital=10_000,
                         broker=PaperBroker(fee_rate=0.001, slippage_bps=0),
                         risk=RiskManager(**defaults))


def test_entry_opens_position_and_reduces_cash():
    e = mk_engine()
    events = e.on_candle_closed("AAAUSDT", [mk_candle(0, 100, 101, 99, 100)])
    assert len(events) == 1 and events[0]["type"] == "open"
    assert "AAAUSDT" in e.positions
    pos = e.positions["AAAUSDT"]
    # riesgo 1% con stop al 5% => nocional 2000, dentro del cap del 20%
    assert abs(pos.qty * pos.entry_price - 2000.0) < 1.0
    assert e.cash < 10_000 - 1999


def test_stop_loss_triggers_intrabar():
    e = mk_engine()
    e.on_candle_closed("AAAUSDT", [mk_candle(0, 100, 101, 99, 100)])
    # vela cuyo mínimo perfora el stop (95)
    candles = [mk_candle(0, 100, 101, 99, 100), mk_candle(300_000, 100, 100.5, 94, 96)]
    events = e.on_candle_closed("AAAUSDT", candles)
    closes = [ev for ev in events if ev["type"] == "close"]
    assert len(closes) == 1
    assert closes[0]["trade"]["exit_reason"] == "stop-loss"
    assert abs(closes[0]["trade"]["exit_price"] - 95.0) < 1e-6
    assert closes[0]["trade"]["pnl"] < 0
    assert "AAAUSDT" not in e.positions


def test_take_profit_triggers_intrabar():
    e = mk_engine()
    e.on_candle_closed("AAAUSDT", [mk_candle(0, 100, 101, 99, 100)])
    candles = [mk_candle(0, 100, 101, 99, 100), mk_candle(300_000, 100, 111, 100, 108)]
    events = e.on_candle_closed("AAAUSDT", candles)
    closes = [ev for ev in events if ev["type"] == "close"]
    assert closes and closes[0]["trade"]["exit_reason"] == "take-profit"
    assert closes[0]["trade"]["pnl"] > 0


def test_equity_conserved_on_flat_price():
    """Sin movimiento de precio, el equity solo baja por comisiones."""
    e = mk_engine()
    e.on_candle_closed("AAAUSDT", [mk_candle(0, 100, 101, 99, 100)])
    eq = e.equity()
    assert 10_000 - 5 < eq < 10_000  # solo la comisión de entrada (2 USDT aprox)


def test_tick_exit_stop():
    e = mk_engine()
    e.on_candle_closed("AAAUSDT", [mk_candle(0, 100, 101, 99, 100)])
    ev = e.check_tick_exit("AAAUSDT", 94.5, ts=600_000)
    assert ev is not None and ev["trade"]["exit_reason"] == "stop-loss"


def test_circuit_breaker_blocks_new_entries():
    e = mk_engine(daily_max_loss_pct=0.02)
    e.on_candle_closed("AAAUSDT", [mk_candle(0, 100, 101, 99, 100)])
    # caída fuerte: el stop salta y el equity queda por debajo del -2% diario
    e.risk.day_start_equity = 20_000  # fuerza pérdida diaria > 2%
    events = e.on_candle_closed("BBBUSDT", [mk_candle(300_000, 100, 101, 99, 100)])
    assert events == []  # no abre nada con el breaker activo
    assert e.risk.halted


def test_max_positions_limit():
    e = mk_engine(max_positions=2)
    for i, sym in enumerate(["AUSDT", "BUSDT", "CUSDT"]):
        e.on_candle_closed(sym, [mk_candle(i, 100, 101, 99, 100)])
    assert len(e.positions) == 2
