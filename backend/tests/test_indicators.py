from app.indicators import atr, ema, highest, rsi, sma
from app.models import Candle


def mk(closes, spread=1.0):
    return [Candle(ts=i * 300_000, open=c, high=c + spread, low=c - spread,
                   close=c, volume=100.0) for i, c in enumerate(closes)]


def test_sma():
    assert sma([1, 2, 3, 4], 2) == 3.5
    assert sma([1, 2], 3) is None


def test_highest():
    assert highest([1, 5, 3], 2) == 5
    assert highest([1], 5) is None


def test_ema_converges_to_constant():
    v = ema([10.0] * 50, 10)
    assert abs(v - 10.0) < 1e-9


def test_rsi_all_gains_is_100():
    closes = [float(i) for i in range(1, 40)]
    assert rsi(closes, 14) == 100.0


def test_rsi_alternating_is_moderate():
    closes = [100 + (1 if i % 2 else -1) for i in range(40)]
    r = rsi(closes, 14)
    assert 30 < r < 70


def test_rsi_insufficient_data():
    assert rsi([1.0, 2.0], 14) is None


def test_atr_constant_range():
    candles = mk([100.0] * 30, spread=1.0)
    a = atr(candles, 14)
    assert abs(a - 2.0) < 1e-6  # high-low = 2 en todas las velas
