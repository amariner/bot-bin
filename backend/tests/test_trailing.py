"""El trailing stop es el cambio con más riesgo de introducir sesgo de futuro:
estos tests fijan que el stop solo suba y que se aplique a partir de la vela
siguiente, nunca dentro de la misma vela que lo movió."""
from app.engine.core import TradingEngine
from app.engine.paper import PaperBroker
from app.engine.risk import RiskManager
from app.models import Candle, Position
from app.strategy.momentum import MomentumBreakout


def c(ts, o, h, l, cl, v=100.0):
    return Candle(ts=ts, open=o, high=h, low=l, close=cl, volume=v)


def base_candles(n=40, price=100.0):
    return [c(i * 3_600_000, price, price + 0.5, price - 0.5, price) for i in range(n)]


def test_trailing_stop_only_moves_up():
    s = MomentumBreakout(trail_atr=3.0, atr_period=14)
    pos = Position(symbol="X", qty=1.0, entry_price=100.0, stop_price=95.0,
                   take_profit=1e6, opened_ts=0, strategy="momentum", reason="t")
    candles = base_candles(30)

    candles.append(c(30 * 3_600_000, 100, 110, 100, 108))
    s.update_position("X", candles, pos)
    raised = pos.stop_price
    assert raised > 95.0, "el stop debe subir cuando el precio sube"

    # vela posterior con máximo menor: el stop NO debe bajar
    candles.append(c(31 * 3_600_000, 108, 108.5, 101, 102))
    s.update_position("X", candles, pos)
    assert pos.stop_price == raised


def test_trailing_anchors_to_peak_not_close():
    s = MomentumBreakout(trail_atr=1.0, atr_period=14)
    pos = Position(symbol="X", qty=1.0, entry_price=100.0, stop_price=95.0,
                   take_profit=1e6, opened_ts=0, strategy="momentum", reason="t")
    candles = base_candles(30)
    candles.append(c(30 * 3_600_000, 100, 120, 99, 101))   # mecha alta, cierre bajo
    s.update_position("X", candles, pos)
    assert pos.meta["peak"] == 120.0


def test_stop_applies_from_next_candle_not_same_one():
    """Sesgo intrabar: el stop movido con el máximo de la vela N no puede
    ejecutarse contra el mínimo de esa misma vela N."""
    class AlwaysBuyTrail(MomentumBreakout):
        def check_entry(self, symbol, candles):
            from app.models import Signal
            if len(candles) < 20:
                return None
            last = candles[-1]
            return Signal(symbol=symbol, entry_price=last.close,
                          stop_price=last.close * 0.90, take_profit=last.close * 1000,
                          reason="test", max_bars=0)

    strat = AlwaysBuyTrail(trail_atr=0.5, atr_period=14)
    engine = TradingEngine(strat, capital=10_000,
                           broker=PaperBroker(fee_rate=0.0, slippage_bps=0),
                           risk=RiskManager(risk_per_trade=0.01, max_positions=5,
                                            daily_max_loss_pct=0.9,
                                            max_notional_pct=0.5, min_notional=5.0))
    candles = base_candles(25)
    engine.on_candle_closed("XUSDT", candles)
    assert "XUSDT" in engine.positions
    stop_after_entry = engine.positions["XUSDT"].stop_price

    # Vela que sube mucho y luego se desploma dentro de la misma vela.
    # Con el orden correcto NO puede cerrarse por el trailing de esta vela.
    candles.append(c(25 * 3_600_000, 100, 130, 96, 97))
    engine.on_candle_closed("XUSDT", candles)
    closes = [t for t in engine.trades]
    if closes:
        # si cerró, solo pudo ser por el stop original (90), no por el trailing
        assert closes[0].exit_price <= stop_after_entry * 1.0001
