"""Diagnóstico decisivo: ¿la estrategia tiene ventaja BRUTA, antes de comisiones?

Ejecuta la mejor configuración con distintos niveles de comisión, incluido 0%.
- Si con 0% de comisión gana => hay señal real y el problema es la fricción
  (se ataca con órdenes límite / descuento BNB / menos operaciones).
- Si con 0% de comisión también pierde => no hay ninguna ventaja que rescatar
  y hay que cambiar de estrategia, no de comisiones.

Uso:
    python scripts/fee_sensitivity.py --symbols 40 --days 240 --timeframe 1h
"""
import argparse
import asyncio
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.backtest.data import download_history
from app.backtest.runner import run_backtest
from app.binance_client import BinancePublic
from app.config import settings, TIMEFRAME_MS
from app.regime import MarketRegime
from app.strategy.momentum import MomentumBreakout
from app.universe import fetch_universe

FEE_LEVELS = [
    (0.0010, "taker estándar 0.10%"),
    (0.00075, "taker con BNB 0.075%"),
    (0.00020, "maker VIP 0.02%"),
    (0.0, "SIN comisiones (ventaja bruta)"),
]


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", type=int, default=40)
    ap.add_argument("--days", type=int, default=240)
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--lookback", type=int, default=20)
    ap.add_argument("--atr-stop", type=float, default=2.0)
    ap.add_argument("--atr-tp", type=float, default=3.0)
    ap.add_argument("--vol-mult", type=float, default=2.5)
    ap.add_argument("--oos-only", action="store_true",
                    help="usar solo el periodo de validación (mismo corte que walkforward.py)")
    ap.add_argument("--split", type=float, default=0.6)
    args = ap.parse_args()

    client = BinancePublic()
    try:
        universe = await fetch_universe(client, size=args.symbols)
        expected = args.days * 86_400_000 // TIMEFRAME_MS[args.timeframe]
        data = {}
        for r in universe:
            candles = await download_history(client, r["symbol"], args.timeframe, args.days)
            if len(candles) >= expected * 0.9:
                data[r["symbol"]] = candles
        btc = await download_history(client, "BTCUSDT", args.timeframe, args.days)
        regime = MarketRegime(btc, 50)

        periodo = f"{args.days} días completos"
        if args.oos_only:
            all_ts = sorted({c.ts for cs in data.values() for c in cs})
            cut = all_ts[int(len(all_ts) * args.split)]
            data = {s: [c for c in cs if c.ts >= cut] for s, cs in data.items()}
            import time as _t
            periodo = ("SOLO validación (datos no vistos) desde "
                       + _t.strftime("%Y-%m-%d", _t.gmtime(cut / 1000)))

        print(f"Config: momentum lb{args.lookback} sl{args.atr_stop} tp{args.atr_tp} "
              f"vol{args.vol_mult} +filtro BTC | {len(data)} símbolos | {periodo}\n")
        print(f"{'comisión':<32}{'ret %':>9}{'maxDD %':>9}{'PF':>7}{'win %':>8}"
              f"{'fees $':>10}{'bruto $':>10}")
        print("-" * 85)
        for fee, name in FEE_LEVELS:
            strat = MomentumBreakout(lookback=args.lookback, atr_stop=args.atr_stop,
                                     atr_tp=args.atr_tp, vol_mult=args.vol_mult)
            r = run_backtest(strat, data, capital=settings.initial_capital,
                             regime=regime, fee_rate=fee, keep_details=False)
            net = r["final_equity"] - settings.initial_capital
            gross = net + r["total_fees"]
            pf = r["profit_factor"]
            print(f"{name:<32}{r['return_pct']:>9.2f}{r['max_drawdown_pct']:>9.2f}"
                  f"{(f'{pf:.2f}' if pf else '–'):>7}{r['win_rate_pct']:>8.1f}"
                  f"{r['total_fees']:>10.0f}{gross:>10.0f}")

        print("\nLectura: si la fila 'SIN comisiones' sigue en negativo, la estrategia no")
        print("tiene ventaja y no se arregla optimizando comisiones.")
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
