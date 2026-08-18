from app.models import Candle
from app.regime import MarketRegime


def series(prices):
    return [Candle(ts=i * 3_600_000, open=p, high=p, low=p, close=p, volume=1.0)
            for i, p in enumerate(prices)]


def test_risk_on_in_uptrend():
    # precio subiendo: siempre por encima de su EMA
    r = MarketRegime(series([100 + i for i in range(120)]), ema_period=50)
    assert r.is_risk_on(119 * 3_600_000) is True


def test_risk_off_in_downtrend():
    r = MarketRegime(series([300 - i for i in range(120)]), ema_period=50)
    assert r.is_risk_on(119 * 3_600_000) is False


def test_defaults_to_risk_on_without_data():
    assert MarketRegime().is_risk_on(0) is True
    # histórico más corto que la EMA: tampoco debe bloquear
    assert MarketRegime(series([100] * 10), ema_period=50).is_risk_on(0) is True


def test_uses_last_known_state_for_future_ts():
    r = MarketRegime(series([300 - i for i in range(120)]), ema_period=50)
    far_future = 10 ** 15
    assert r.is_risk_on(far_future) is False


def test_engine_blocks_entries_when_risk_off():
    from tests.test_engine import AlwaysBuy, mk_candle
    from app.engine.core import TradingEngine
    from app.engine.paper import PaperBroker
    from app.engine.risk import RiskManager

    risk_off = MarketRegime(series([300 - i for i in range(120)]), ema_period=50)
    engine = TradingEngine(AlwaysBuy(), capital=10_000,
                           broker=PaperBroker(fee_rate=0.001, slippage_bps=0),
                           risk=RiskManager(), regime=risk_off)
    events = engine.on_candle_closed("AAAUSDT", [mk_candle(200 * 3_600_000, 100, 101, 99, 100)])
    # no abre posición, pero informa del descarte con un evento
    assert "AAAUSDT" not in engine.positions
    assert len(events) == 1
    assert events[0]["type"] == "signal_skipped"
    assert "BTC" in events[0]["reason"]
    assert engine.signals_seen == 1
    assert engine.signals_rejected_regime == 1
