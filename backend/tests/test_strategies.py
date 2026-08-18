import math

from app.models import Candle
from app.strategy.momentum import MomentumBreakout
from app.strategy.meanrev import MeanReversionRSI


def flat_candles(n, price=100.0, vol=100.0, tf=300_000):
    out = []
    for i in range(n):
        # pequeño zigzag para que ATR y RSI no degeneren
        c = price + (0.2 if i % 2 else -0.2)
        out.append(Candle(ts=i * tf, open=price, high=c + 0.5, low=c - 0.5,
                          close=c, volume=vol))
    return out


def test_momentum_no_signal_in_flat_market():
    s = MomentumBreakout()
    assert s.check_entry("X", flat_candles(60)) is None


def test_momentum_signals_on_breakout_with_volume():
    s = MomentumBreakout(lookback=20)
    candles = flat_candles(59)
    last_ts = candles[-1].ts + 300_000
    # vela alcista que rompe el rango con 3x volumen
    candles.append(Candle(ts=last_ts, open=100.0, high=106.0, low=100.0,
                          close=105.0, volume=300.0))
    sig = s.check_entry("X", candles)
    assert sig is not None
    assert sig.stop_price < sig.entry_price < sig.take_profit
    # relación riesgo/beneficio 1:1.5 (2 ATR vs 3 ATR)
    rr = (sig.take_profit - sig.entry_price) / (sig.entry_price - sig.stop_price)
    assert abs(rr - 1.5) < 1e-6


def test_momentum_rejects_breakout_without_volume():
    s = MomentumBreakout(lookback=20)
    candles = flat_candles(59)
    candles.append(Candle(ts=candles[-1].ts + 300_000, open=100.0, high=106.0,
                          low=100.0, close=105.0, volume=100.0))  # volumen normal
    assert s.check_entry("X", candles) is None


def _downtrend_after_uptrend(n_up=220, n_down=12):
    """Serie alcista sostenida y luego caída brusca: RSI en sobreventa
    con el precio todavía por encima de la EMA200."""
    candles = []
    price = 100.0
    for i in range(n_up):
        price *= 1.004
        candles.append(Candle(ts=i * 300_000, open=price / 1.004, high=price * 1.001,
                              low=price / 1.004 * 0.999, close=price, volume=100.0))
    for j in range(n_down):
        prev = price
        price *= 0.9915
        candles.append(Candle(ts=(n_up + j) * 300_000, open=prev, high=prev,
                              low=price * 0.999, close=price, volume=100.0))
    return candles


def test_meanrev_signals_on_dip_in_uptrend():
    s = MeanReversionRSI()
    sig = s.check_entry("X", _downtrend_after_uptrend())
    assert sig is not None
    assert sig.stop_price < sig.entry_price < sig.take_profit


def test_meanrev_no_signal_without_oversold():
    s = MeanReversionRSI()
    assert s.check_entry("X", flat_candles(250)) is None
