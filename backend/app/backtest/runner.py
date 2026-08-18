"""Backtest de cartera multi-símbolo sobre el TradingEngine real.

Alinea las velas de todos los símbolos por timestamp y las procesa en orden
cronológico, igual que llegarían en vivo. Métricas: retorno, drawdown máximo,
win rate, profit factor y desglose diario.
"""
from collections import defaultdict
from typing import Dict, List, Optional

from ..models import Candle
from ..engine.core import TradingEngine
from ..engine.paper import PaperBroker
from ..engine.risk import RiskManager
from ..strategy.base import Strategy


def run_backtest(strategy: Strategy, data: Dict[str, List[Candle]],
                 capital: float = 10_000.0, history: Optional[int] = None,
                 regime=None, fee_rate: Optional[float] = None,
                 keep_details: bool = True) -> dict:
    # Ventana justa para los indicadores: acelera el backtest sin cambiar resultados
    if history is None:
        history = max(strategy.warmup + 10, 60)
    broker = PaperBroker(fee_rate=fee_rate) if fee_rate is not None else None
    engine = TradingEngine(strategy, capital=capital, broker=broker, regime=regime)

    # Índice cronológico: ts -> [(symbol, idx_vela)]
    timeline = defaultdict(list)
    for sym, candles in data.items():
        for i, c in enumerate(candles):
            timeline[c.ts].append((sym, i))
    timestamps = sorted(timeline)

    equity_curve: List[dict] = []
    seen: Dict[str, int] = {}
    for ts in timestamps:
        for sym, idx in timeline[ts]:
            seen[sym] = idx
            start = max(0, idx + 1 - history)
            window = data[sym][start: idx + 1]
            if len(window) < strategy.warmup:
                continue
            engine.on_candle_closed(sym, window)
        equity_curve.append({"ts": ts, "equity": engine.equity()})

    if timestamps:
        engine.liquidate_all(timestamps[-1], "fin de backtest")
        equity_curve.append({"ts": timestamps[-1], "equity": engine.equity()})

    return _metrics(engine, equity_curve, capital, keep_details)


def _metrics(engine: TradingEngine, equity_curve: List[dict], capital: float,
             keep_details: bool = True) -> dict:
    trades = engine.trades
    final = equity_curve[-1]["equity"] if equity_curve else capital
    wins = [t for t in trades if t.pnl > 0]
    losses = [t for t in trades if t.pnl <= 0]
    gross_win = sum(t.pnl for t in wins)
    gross_loss = -sum(t.pnl for t in losses)

    peak, max_dd = -1e18, 0.0
    for p in equity_curve:
        peak = max(peak, p["equity"])
        if peak > 0:
            max_dd = max(max_dd, (peak - p["equity"]) / peak)

    daily = defaultdict(float)
    for t in trades:
        daily[t.exit_ts // 86_400_000] += t.pnl
    positive_days = sum(1 for v in daily.values() if v > 0)

    return {
        "strategy": engine.strategy.name,
        "initial_capital": capital,
        "final_equity": round(final, 2),
        "return_pct": round((final / capital - 1) * 100, 2),
        "max_drawdown_pct": round(max_dd * 100, 2),
        "trades": len(trades),
        "win_rate_pct": round(len(wins) / len(trades) * 100, 1) if trades else 0.0,
        "profit_factor": round(gross_win / gross_loss, 2) if gross_loss > 0 else None,
        "total_fees": round(sum(t.fees for t in trades), 2),
        "avg_pnl": round(sum(t.pnl for t in trades) / len(trades), 4) if trades else 0.0,
        "trading_days": len(daily),
        "positive_days": positive_days,
        "positive_days_pct": round(positive_days / len(daily) * 100, 1) if daily else 0.0,
        "expectancy_pct": round(sum(t.pnl for t in trades) / len(trades) / capital * 100, 4)
                          if trades else 0.0,
        "equity_curve": equity_curve if keep_details else [],
        "trade_list": [t.to_dict() for t in trades] if keep_details else [],
    }
