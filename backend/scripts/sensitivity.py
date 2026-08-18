"""¿La configuración ganadora es una meseta o un pico de suerte?

Una configuración creíble está rodeada de vecinas que también funcionan: si
mover el volumen de 4.0 a 3.5 o el trailing de 3.0 a 2.5 destruye el resultado,
lo que se encontró fue ruido, no una propiedad del mercado.

Se evalúa sobre los símbolos NUNCA usados para ajustar, que es donde el
resultado significa algo.

Uso:
    python scripts/sensitivity.py
"""
import argparse
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.backtest.data import download_history
from app.backtest.lab import buy_and_hold, describe, run_grid
from app.binance_client import BinancePublic
from app.config import settings, TIMEFRAME_MS
from app.universe import fetch_universe

FEE = 0.00075

# Ganadora del proceso de validación en 4h
BASE = {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0, "trail_atr": 3.0,
        "trend_ema": 0, "max_bars": 0, "regime": True}


async def load(client, symbols, timeframe, days):
    expected = days * 86_400_000 // TIMEFRAME_MS[timeframe]
    data = {}
    for sym in symbols:
        cs = await download_history(client, sym, timeframe, days)
        if len(cs) >= expected * 0.9:
            data[sym] = cs
    return data


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--days", type=int, default=240)
    args = ap.parse_args()

    client = BinancePublic()
    try:
        universe = await fetch_universe(client, size=80)
        fresh = await load(client, [r["symbol"] for r in universe[40:80]],
                           args.timeframe, args.days)
        btc = await download_history(client, "BTCUSDT", args.timeframe, args.days)
    finally:
        await client.close()

    all_ts = sorted({c.ts for cs in fresh.values() for c in cs})
    lo, hi = all_ts[0], all_ts[-1] + 1
    bh = buy_and_hold(fresh, lo, hi)["return_pct"]
    print(f"{len(fresh)} símbolos nunca usados · {args.timeframe} · "
          f"comprar y mantener {bh:+.2f}%\n")

    axes = {
        "vol_mult": [2.5, 3.0, 4.0, 5.0, 6.0],
        "trail_atr": [2.0, 2.5, 3.0, 3.5, 4.0],
        "atr_stop": [1.5, 2.0, 2.5, 3.0],
        "trend_ema": [0, 50, 100, 200],
        "lookback": [10, 20, 30, 40],
    }

    summary = {}
    for axis, values in axes.items():
        configs = []
        for v in values:
            cfg = dict(BASE)
            cfg[axis] = v
            configs.append(cfg)
        results = run_grid(configs, fresh, btc, lo, hi, FEE)
        print(f"--- variando {axis} (resto fijo) ---")
        print(f"{'valor':>8}{'ret %':>10}{'vs B&H':>9}{'PF':>7}{'trades':>8}{'maxDD%':>9}")
        rows = []
        for v, r in zip(values, results):
            pf = r["profit_factor"]
            rows.append({"value": v, "return_pct": r["return_pct"],
                         "profit_factor": pf, "trades": r["trades"],
                         "max_drawdown_pct": r["max_drawdown_pct"]})
            mark = "  <- base" if v == BASE.get(axis) else ""
            print(f"{str(v):>8}{r['return_pct']:>10.2f}{r['return_pct'] - bh:>9.2f}"
                  f"{(f'{pf:.2f}' if pf else '–'):>7}{r['trades']:>8}"
                  f"{r['max_drawdown_pct']:>9.2f}{mark}")
        positive = sum(1 for x in rows if x["return_pct"] > 0)
        print(f"    {positive}/{len(rows)} valores en positivo\n")
        summary[axis] = {"rows": rows, "positive": positive, "total": len(rows)}

    total_pos = sum(s["positive"] for s in summary.values())
    total = sum(s["total"] for s in summary.values())
    print("=" * 60)
    print(f"MESETA: {total_pos}/{total} variantes en positivo "
          f"({total_pos / total * 100:.0f}%)")
    if total_pos / total >= 0.7:
        print("=> Superficie estable: el resultado NO depende de valores exactos.")
    elif total_pos / total >= 0.5:
        print("=> Meseta parcial: hay señal, pero sensible a algunos parámetros.")
    else:
        print("=> Pico aislado: probablemente sobreajuste. Desconfiar.")

    path = os.path.join(settings.data_dir, "sensitivity.json")
    with open(path, "w") as f:
        json.dump({"generated_at": int(time.time() * 1000), "base": BASE,
                   "benchmark": bh, "timeframe": args.timeframe,
                   "axes": summary,
                   "plateau_pct": round(total_pos / total * 100, 1)}, f, indent=1)
    print(f"Guardado en {path}")


if __name__ == "__main__":
    asyncio.run(main())
