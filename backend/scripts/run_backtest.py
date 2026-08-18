"""Backtest comparativo de estrategias sobre el top-N del universo.

Uso:
    python -m scripts.run_backtest --symbols 20 --days 30 [--timeframe 5m]

Descarga (con caché) las velas y ejecuta todas las estrategias registradas con
la misma configuración de riesgo. Imprime una tabla comparativa y guarda el
detalle en data/backtest_<estrategia>.json.
"""
import argparse
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.backtest.data import download_history
from app.backtest.runner import run_backtest
from app.binance_client import BinancePublic
from app.config import settings
from app.strategy import STRATEGIES, make_strategy
from app.universe import fetch_universe


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=20, help="nº de símbolos top por volumen")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--timeframe", default=settings.timeframe)
    ap.add_argument("--capital", type=float, default=settings.initial_capital)
    args = ap.parse_args()

    client = BinancePublic()
    try:
        universe = await fetch_universe(client, size=args.symbols)
        symbols = [r["symbol"] for r in universe]
        print(f"Universo ({len(symbols)}): {', '.join(symbols)}")

        data = {}
        for i, sym in enumerate(symbols):
            candles = await download_history(client, sym, args.timeframe, args.days)
            data[sym] = candles
            print(f"  [{i+1}/{len(symbols)}] {sym}: {len(candles)} velas")

        print(f"\n{'estrategia':<12}{'retorno %':>10}{'maxDD %':>9}{'trades':>8}"
              f"{'win %':>8}{'PF':>6}{'días+ %':>9}{'fees':>8}")
        print("-" * 70)
        for name in STRATEGIES:
            result = run_backtest(make_strategy(name), data, capital=args.capital)
            print(f"{name:<12}{result['return_pct']:>10.2f}{result['max_drawdown_pct']:>9.2f}"
                  f"{result['trades']:>8}{result['win_rate_pct']:>8.1f}"
                  f"{str(result['profit_factor']):>6}{result['positive_days_pct']:>9.1f}"
                  f"{result['total_fees']:>8.1f}")
            out = os.path.join(settings.data_dir, f"backtest_{name}.json")
            with open(out, "w") as f:
                json.dump(result, f, indent=1)
        print(f"\nDetalle guardado en {settings.data_dir}/backtest_<estrategia>.json")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
