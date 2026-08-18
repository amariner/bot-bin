import random

from app.backtest.runner import run_backtest
from app.models import Candle
from app.strategy.momentum import MomentumBreakout


def synthetic_series(seed, n=800, start=100.0):
    rng = random.Random(seed)
    candles = []
    price = start
    for i in range(n):
        drift = rng.gauss(0.0002, 0.004)
        o = price
        c = price * (1 + drift)
        hi = max(o, c) * (1 + abs(rng.gauss(0, 0.001)))
        lo = min(o, c) * (1 - abs(rng.gauss(0, 0.001)))
        vol = abs(rng.gauss(100, 40)) + 10
        candles.append(Candle(ts=i * 300_000, open=o, high=hi, low=lo, close=c, volume=vol))
        price = c
    return candles


def test_backtest_runs_and_reports_metrics():
    data = {f"S{i}USDT": synthetic_series(i) for i in range(3)}
    result = run_backtest(MomentumBreakout(), data, capital=10_000)
    assert result["strategy"] == "momentum"
    assert result["initial_capital"] == 10_000
    assert isinstance(result["trades"], int)
    assert result["equity_curve"], "curva de equity vacía"
    # el equity final coincide con capital + suma de PnL de los trades
    total_pnl = sum(t["pnl"] for t in result["trade_list"])
    assert abs(result["final_equity"] - (10_000 + total_pnl)) < 0.01


def test_backtest_no_positions_left_open():
    data = {f"S{i}USDT": synthetic_series(i + 100) for i in range(2)}
    result = run_backtest(MomentumBreakout(), data, capital=10_000)
    # liquidamos al final: el nº de trades es par de entradas/salidas completas
    assert all(t["exit_ts"] >= t["entry_ts"] for t in result["trade_list"])
