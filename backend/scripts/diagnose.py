"""Diagnóstico por régimen de mercado.

Pregunta: ¿la ventaja depende de si el mercado sube o baja? Ejecuta una
configuración en ventanas temporales sucesivas sobre DOS conjuntos de símbolos
(los usados para ajustar y otros nunca vistos), y muestra su resultado junto al
del mercado en esa misma ventana.

Si el bot gana solo cuando el mercado cae, no es una máquina de ganar dinero:
es una cobertura, y hay que decirlo con esas palabras.

Uso:
    python scripts/diagnose.py --preset momentum_trail --windows 6
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
from app.strategy import PRESETS
from app.universe import fetch_universe

FEE = 0.00075   # escenario realista con BNB

PRESET_CFG = {
    "momentum_4h": {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0,
                    "trail_atr": 3.0, "max_bars": 0, "regime": True},
    "momentum_trail": {"lookback": 20, "vol_mult": 4.0, "atr_stop": 2.0,
                       "trail_atr": 3.0, "max_bars": 0, "trend_ema": 100, "regime": True},
    "momentum": {"lookback": 20, "vol_mult": 2.5, "atr_stop": 2.0, "atr_tp": 3.0,
                 "regime": True},
}


async def load(client, symbols, timeframe, days):
    expected = days * 86_400_000 // TIMEFRAME_MS[timeframe]
    data = {}
    for sym in symbols:
        cs = await download_history(client, sym, timeframe, days)
        if len(cs) >= expected * 0.9:
            data[sym] = cs
    return data


def windows(data, n):
    all_ts = sorted({c.ts for cs in data.values() for c in cs})
    step = len(all_ts) // n
    out = []
    for i in range(n):
        lo = all_ts[i * step]
        hi = all_ts[(i + 1) * step] if i < n - 1 else all_ts[-1] + 1
        out.append((lo, hi))
    return out


def d(ts):
    return time.strftime("%d %b", time.gmtime(ts / 1000))


def report(title, data, btc, cfg, wins):
    print(f"\n{'=' * 88}\n{title}\n{'=' * 88}")
    print(f"{'ventana':<18}{'mercado %':>11}{'bot %':>9}{'dif':>9}{'PF':>7}"
          f"{'trades':>8}{'maxDD%':>9}")
    print("-" * 88)
    rows = []
    for lo, hi in wins:
        r = run_grid([cfg], data, btc, lo, hi, FEE)[0]
        bh = buy_and_hold(data, lo, hi)["return_pct"]
        pf = r["profit_factor"]
        rows.append({"from": lo, "to": hi, "market": bh, "bot": r["return_pct"],
                     "pf": pf, "trades": r["trades"], "dd": r["max_drawdown_pct"]})
        print(f"{d(lo) + ' → ' + d(hi):<18}{bh:>11.2f}{r['return_pct']:>9.2f}"
              f"{r['return_pct'] - bh:>9.2f}{(f'{pf:.2f}' if pf else '–'):>7}"
              f"{r['trades']:>8}{r['max_drawdown_pct']:>9.2f}")
    return rows


def summarize(rows, label):
    up = [r for r in rows if r["market"] > 0]
    down = [r for r in rows if r["market"] <= 0]
    def avg(xs, k):
        return sum(x[k] for x in xs) / len(xs) if xs else 0.0
    print(f"\n{label}")
    print(f"  ventanas ALCISTAS ({len(up)}): mercado {avg(up,'market'):+.2f}% · "
          f"bot {avg(up,'bot'):+.2f}%  => diferencia {avg(up,'bot') - avg(up,'market'):+.2f}")
    print(f"  ventanas BAJISTAS ({len(down)}): mercado {avg(down,'market'):+.2f}% · "
          f"bot {avg(down,'bot'):+.2f}%  => diferencia {avg(down,'bot') - avg(down,'market'):+.2f}")
    return {"up": up, "down": down}


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default="momentum_trail")
    ap.add_argument("--windows", type=int, default=6)
    ap.add_argument("--timeframe", default="1h")
    ap.add_argument("--days", type=int, default=240)
    args = ap.parse_args()

    cfg = PRESET_CFG[args.preset]
    client = BinancePublic()
    try:
        universe = await fetch_universe(client, size=80)
        fitted = await load(client, [r["symbol"] for r in universe[:40]],
                            args.timeframe, args.days)
        fresh = await load(client, [r["symbol"] for r in universe[40:80]],
                           args.timeframe, args.days)
        btc = await download_history(client, "BTCUSDT", args.timeframe, args.days)
    finally:
        await client.close()

    print(f"Configuración: {describe(cfg)} · comisión {FEE * 100:.3f}%")
    wins = windows(fitted, args.windows)
    rows_a = report(f"CONJUNTO A — {len(fitted)} símbolos usados para ajustar",
                    fitted, btc, cfg, wins)
    rows_b = report(f"CONJUNTO B — {len(fresh)} símbolos NUNCA usados",
                    fresh, btc, cfg, windows(fresh, args.windows))

    print("\n" + "=" * 88)
    print("¿DEPENDE DEL RÉGIMEN DE MERCADO?")
    print("=" * 88)
    summarize(rows_a, "Conjunto A (ajustado):")
    summarize(rows_b, "Conjunto B (nunca visto):")

    allrows = rows_a + rows_b
    up = [r for r in allrows if r["market"] > 0]
    down = [r for r in allrows if r["market"] <= 0]
    beat_up = sum(1 for r in up if r["bot"] > r["market"])
    beat_down = sum(1 for r in down if r["bot"] > r["market"])
    print(f"\nBate al mercado en {beat_up}/{len(up)} ventanas alcistas "
          f"y en {beat_down}/{len(down)} ventanas bajistas.")

    path = os.path.join(settings.data_dir, "diagnose.json")
    with open(path, "w") as f:
        json.dump({"preset": args.preset, "config": cfg, "fee": FEE,
                   "fitted": rows_a, "fresh": rows_b}, f, indent=1)
    print(f"Guardado en {path}")


if __name__ == "__main__":
    asyncio.run(main())
